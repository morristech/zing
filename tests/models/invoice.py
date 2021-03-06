# -*- coding: utf-8 -*-
#
# Copyright (C) Zing contributors.
#
# This file is a part of the Zing project. It is distributed under the GPL3
# or later license. See the LICENSE file for a copy of the license and the
# AUTHORS file for copyright and authorship information.

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from tests.factories import (PaidTaskFactory, SubmissionFactory,
                             ScoreLogFactory, UserFactory)

from pootle_statistics.models import (SubmissionFields, SubmissionTypes,
                                      TranslationActionCodes)
from reports.models.invoice import Invoice, MONTH_FORMAT, get_previous_month
from reports.models.paidtask import PaidTask, PaidTaskTypes


FAKE_CONFIG = {
    'name': 'Foo',
    'paid_by': 'Bar',
    'wire_info': 'Baz 01234',
}


FAKE_EMAIL_CONFIG = dict({
    'email': 'foo@example.org',
    'accounting_email': 'bar@example.com',
}, **FAKE_CONFIG)


@pytest.fixture()
def invoice_directory(settings, tmpdir):
    """Sets up a tmp invoices directory."""
    invoices_dir = tmpdir.mkdir('invoices')
    settings.ZING_INVOICES_DIRECTORY = str(invoices_dir)
    return invoices_dir


@pytest.mark.parametrize('month', [
    None, timezone.now(), timezone.datetime(2014, 04, 01),
])
def test_invoice_repr(month):
    user = UserFactory.build()
    format_month = get_previous_month() if month is None else month
    assert (
        repr(Invoice(user, FAKE_CONFIG, month=month)) == u'<Invoice %s:%s>'
        % (user.username, format_month.strftime(MONTH_FORMAT))
    )


@pytest.mark.parametrize('config, require_email_fields', [
    ({}, False),
    ({
        'foo': None,
        'bar': False,
    }, False),
    ({
        'name': None,
        'paid_by': None,
    }, False),
    ({
        'name': None,
        'paid_by': None,
        'wire_info': None,
    }, True),
    ({
        'name': None,
        'paid_by': None,
        'wire_info': None,
        'email': None,
    }, True),
    ({
        'name': None,
        'paid_by': None,
        'wire_info': None,
        'accounting_email': None,
    }, True),
])
def test_invoice_check_config_for(config, require_email_fields):
    with pytest.raises(ImproperlyConfigured):
        Invoice.check_config_for(config, 'fake_username',
                                 require_email_fields=require_email_fields)


@pytest.mark.django_db
def test_invoice_get_rates_inconsistent_scorelog_rates(member, store0):
    USER_RATE_ONE = 0.5
    USER_RATE_TWO = 0.2

    # Set some rate
    member.rate = USER_RATE_ONE
    member.review_rate = USER_RATE_ONE
    member.save()

    month = timezone.datetime(2014, 04, 01)

    submission_kwargs = {
        'store': store0,
        'unit': store0.units[0],
        'field': SubmissionFields.TARGET,
        'type': SubmissionTypes.NORMAL,
        'old_value': 'foo',
        'new_value': 'bar',
        'submitter': member,
        'translation_project': store0.translation_project,
        'creation_time': month,
    }
    scorelog_kwargs = {
        'wordcount': 1,
        'similarity': 0,
        'action_code': TranslationActionCodes.NEW,
        'creation_time': month,
        'user': member,
        'submission': SubmissionFactory(**submission_kwargs),
    }

    ScoreLogFactory(**scorelog_kwargs)

    # Alter rates, producing an inconsistent state when recording the ScoreLog
    member.rate = USER_RATE_TWO
    member.review_rate = USER_RATE_TWO
    member.save()

    submission_kwargs['unit'] = store0.units[1]
    scorelog_kwargs['submission'] = SubmissionFactory(**submission_kwargs)

    ScoreLogFactory(**scorelog_kwargs)
    invoice = Invoice(member, FAKE_CONFIG, month=month)

    with pytest.raises(ValueError) as e:
        invoice.get_rates()

    assert (
        'Multiple rate values recorded for user %s' % (member.username, )
        in e.value.message
    )


@pytest.mark.django_db
@pytest.mark.parametrize('task_type, task_type_name, user_rate_attr_name', [
    (PaidTaskTypes.TRANSLATION, 'TRANSLATION', 'rate'),
    (PaidTaskTypes.REVIEW, 'REVIEW', 'review_rate'),
])
def test_invoice_get_rates_inconsistent_paidtask_rates(member, task_type,
                                                       task_type_name,
                                                       user_rate_attr_name,
                                                       store0):
    USER_RATE = 0.5
    PAID_TASK_RATE = 0.2

    # Set some user rate
    setattr(member, user_rate_attr_name, USER_RATE)
    member.save()

    month = timezone.datetime(2014, 04, 01)

    submission_kwargs = {
        'store': store0,
        'unit': store0.units[0],
        'field': SubmissionFields.TARGET,
        'type': SubmissionTypes.NORMAL,
        'old_value': 'foo',
        'new_value': 'bar',
        'submitter': member,
        'translation_project': store0.translation_project,
        'creation_time': month,
    }
    scorelog_kwargs = {
        'wordcount': 1,
        'similarity': 0,
        'action_code': TranslationActionCodes.NEW,
        'creation_time': month,
        'user': member,
        'submission': SubmissionFactory(**submission_kwargs),
    }
    paid_task_kwargs = {
        'rate': PAID_TASK_RATE,  # Note how this doesn't match user's rate
        'datetime': month,
        'user': member,
        'task_type': task_type,
    }

    ScoreLogFactory(**scorelog_kwargs)
    PaidTaskFactory(**paid_task_kwargs)
    invoice = Invoice(member, FAKE_CONFIG, month=month)

    with pytest.raises(ValueError) as e:
        invoice.get_rates()

    assert (
        'Multiple %s rate values for user %s' % (task_type_name,
                                                 member.username)
        in e.value.message
    )


@pytest.mark.django_db
def test_invoice_get_rates_inconsistent_hourly_paidtask_rates(member):
    PAID_TASK_RATE_ONE = 0.5
    PAID_TASK_RATE_TWO = 0.2

    month = timezone.datetime(2014, 04, 01)

    paid_task_kwargs = {
        'rate': PAID_TASK_RATE_ONE,  # Note how this doesn't match user's rate
        'datetime': month,
        'user': member,
        'task_type': PaidTaskTypes.HOURLY_WORK,
    }

    PaidTaskFactory(**paid_task_kwargs)
    PaidTaskFactory(**dict(paid_task_kwargs, rate=PAID_TASK_RATE_TWO))
    invoice = Invoice(member, FAKE_CONFIG, month=month)

    with pytest.raises(ValueError) as e:
        invoice.get_rates()

    assert (
        'Multiple HOURLY_WORK rate values for user %s' % (member.username)
        in e.value.message
    )


@pytest.mark.django_db
@pytest.mark.parametrize('task_type, task_type_name, user_rate_attr_name', [
    (PaidTaskTypes.TRANSLATION, 'TRANSLATION', 'rate'),
    (PaidTaskTypes.REVIEW, 'REVIEW', 'review_rate'),
])
def test_invoice_get_rates_scorelog_rates(member, task_type, task_type_name,
                                          user_rate_attr_name, store0):
    """Tests that `Invoice.get_rates()` returns the rates set for users in their
    `ScoreLog` entries.
    """
    USER_RATE_ONE = 0.5
    USER_RATE_TWO = 0.2

    # Set some user rate
    setattr(member, user_rate_attr_name, USER_RATE_ONE)
    member.save()

    month = timezone.datetime(2014, 04, 01)

    submission_kwargs = {
        'store': store0,
        'unit': store0.units[0],
        'field': SubmissionFields.TARGET,
        'type': SubmissionTypes.NORMAL,
        'old_value': 'foo',
        'new_value': 'bar',
        'submitter': member,
        'translation_project': store0.translation_project,
        'creation_time': month,
    }
    scorelog_kwargs = {
        'wordcount': 1,
        'similarity': 0,
        'action_code': TranslationActionCodes.NEW,
        'creation_time': month,
        'user': member,
        'submission': SubmissionFactory(**submission_kwargs),
    }

    ScoreLogFactory(**scorelog_kwargs)
    invoice = Invoice(member, FAKE_CONFIG, month=month)

    # Set user rate to something else to ensure we get the recorded rates
    setattr(member, user_rate_attr_name, USER_RATE_TWO)
    member.save()

    rate, review_rate, hourly_rate = invoice.get_rates()
    assert locals()[user_rate_attr_name] == USER_RATE_ONE


@pytest.mark.django_db
def test_invoice_get_rates_paidtask_rates(member):
    """Tests that `Invoice.get_rates()` returns the rates set for users in their
    `PaidTask` entries.
    """
    USER_RATE_ONE = 0.5
    USER_RATE_TWO = 0.2

    # Set some user rate
    member.hourly_rate = USER_RATE_ONE
    member.save()

    month = timezone.datetime(2014, 04, 01)

    paid_task_kwargs = {
        'rate': USER_RATE_ONE,
        'datetime': month,
        'user': member,
        'task_type': PaidTaskTypes.HOURLY_WORK,
    }
    PaidTaskFactory(**paid_task_kwargs)

    invoice = Invoice(member, FAKE_CONFIG, month=month)

    # Set user rate to something else to ensure we get the recorded rates
    member.hourly_rate = USER_RATE_TWO
    member.save()

    rate, review_rate, hourly_rate = invoice.get_rates()
    assert hourly_rate == USER_RATE_ONE


@pytest.mark.django_db
def test_invoice_get_rates_user(member):
    """Tests that `Invoice.get_rates()` returns the rates set for users in their
    user model.
    """
    USER_RATE = 0.5

    # Set some user rate
    member.rate = USER_RATE
    member.review_rate = USER_RATE
    member.hourly_rate = USER_RATE
    member.save()

    month = timezone.datetime(2014, 04, 01)
    invoice = Invoice(member, FAKE_CONFIG, month=month)

    rate, review_rate, hourly_rate = invoice.get_rates()
    assert rate == USER_RATE
    assert review_rate == USER_RATE
    assert hourly_rate == USER_RATE


@pytest.mark.django_db
@pytest.mark.parametrize('task_type', (PaidTaskTypes.TRANSLATION,
                                       PaidTaskTypes.REVIEW,
                                       PaidTaskTypes.HOURLY_WORK,
                                       PaidTaskTypes.CORRECTION))
@pytest.mark.parametrize('action_code', (TranslationActionCodes.NEW,
                                         TranslationActionCodes.REVIEWED))
def test_invoice_get_user_amounts(member, action_code, task_type):
    """Tests that `Invoice._get_user_amounts()` returns the total amount of work
    performed for the given user when their activities were recorded via both
    score logs and paid tasks.
    """
    from pootle_statistics.models import Submission
    EVENT_COUNT = 5
    WORDCOUNT = 5
    TASK_COUNT = 5
    PAID_TASK_AMOUNT = 22
    month = timezone.datetime(2014, 04, 01)

    for i in range(EVENT_COUNT):
        scorelog_kwargs = {
            'wordcount': WORDCOUNT,
            'similarity': 0,
            'action_code': action_code,
            'creation_time': month,
            'user': member,
            'submission': Submission.objects.all()[i],
        }
        ScoreLogFactory(**scorelog_kwargs)

    for i in range(TASK_COUNT):
        paid_task_kwargs = {
            'amount': PAID_TASK_AMOUNT,
            'datetime': month,
            'user': member,
            'task_type': task_type,
        }
        PaidTaskFactory(**paid_task_kwargs)

    invoice = Invoice(member, FAKE_CONFIG, month=month)

    translated, reviewed, hours, correction = invoice._get_user_amounts(member)

    if (action_code == TranslationActionCodes.NEW and
        task_type == PaidTaskTypes.TRANSLATION):
        assert translated == (EVENT_COUNT * WORDCOUNT +
                              TASK_COUNT * PAID_TASK_AMOUNT)
    elif action_code == TranslationActionCodes.NEW:
        assert translated == EVENT_COUNT * WORDCOUNT
    elif task_type == PaidTaskTypes.TRANSLATION:
        assert translated == TASK_COUNT * PAID_TASK_AMOUNT
    else:
        assert translated == 0

    if (action_code == TranslationActionCodes.REVIEWED and
        task_type == PaidTaskTypes.REVIEW):
        assert reviewed == (EVENT_COUNT * WORDCOUNT +
                            TASK_COUNT * PAID_TASK_AMOUNT)
    elif action_code == TranslationActionCodes.REVIEWED:
        assert reviewed == EVENT_COUNT * WORDCOUNT
    elif task_type == PaidTaskTypes.REVIEW:
        assert reviewed == TASK_COUNT * PAID_TASK_AMOUNT
    else:
        assert reviewed == 0

    if task_type == PaidTaskTypes.HOURLY_WORK:
        assert hours == TASK_COUNT * PAID_TASK_AMOUNT
    else:
        assert hours == 0

    if task_type == PaidTaskTypes.CORRECTION:
        assert correction == TASK_COUNT * PAID_TASK_AMOUNT
    else:
        assert correction == 0


@pytest.mark.django_db
def test_invoice_amounts_below_minimal_payment(member, monkeypatch):
    """Tests total amounts' correctness when the accrued total is below the
    minimal payment bar.
    """
    config = dict({
        'minimal_payment': 10,
        'extra_add': 5,
    }, **FAKE_CONFIG)
    invoice = Invoice(member, config, add_correction=True)

    rates = (0.5, 0.5, 0.5)
    monkeypatch.setattr(invoice, 'get_rates', lambda: rates)
    amounts = (5, 5, 5, 0)
    monkeypatch.setattr(invoice, '_get_full_user_amounts', lambda x: amounts)

    invoice.generate()

    assert invoice.amounts['subtotal'] == 3 * (amounts[0] * rates[0])
    assert invoice.amounts['balance'] == 3 * (amounts[0] * rates[0])
    assert invoice.amounts['total'] == 0
    assert invoice.amounts['extra_amount'] == 0


@pytest.mark.django_db
def test_invoice_amounts_with_extra_add(member, monkeypatch):
    """Tests total amounts' correctness when there is an extra amount to be
    added to the accrued total.
    """
    extra_add = 5
    user = UserFactory.build()
    config = dict({
        'extra_add': extra_add,
    }, **FAKE_CONFIG)
    invoice = Invoice(user, config, add_correction=True)

    rates = (0.5, 0.5, 0.5)
    monkeypatch.setattr(invoice, 'get_rates', lambda: rates)
    amounts = (5, 5, 5, 0)
    monkeypatch.setattr(invoice, '_get_full_user_amounts', lambda x: amounts)

    invoice.generate()

    assert invoice.amounts['subtotal'] == 3 * (amounts[0] * rates[0])
    assert invoice.amounts['balance'] is None
    assert invoice.amounts['total'] == 3 * (amounts[0] * rates[0]) + extra_add
    assert invoice.amounts['extra_amount'] == extra_add


def _check_single_paidtask(invoice, amount):
    server_tz = timezone.get_default_timezone()
    local_now = timezone.localtime(invoice.now, server_tz)
    current_month_start = local_now.replace(day=1, hour=0, minute=0, second=0,
                                            microsecond=0)
    PaidTask.objects.get(
        task_type=PaidTaskTypes.CORRECTION,
        amount=(-1) * amount,
        datetime=invoice.month_end,
        description='Carryover to the next month',
        user=invoice.user,
    )
    PaidTask.objects.get(
        task_type=PaidTaskTypes.CORRECTION,
        amount=amount,
        datetime=current_month_start,
        description='Carryover from the previous month',
        user=invoice.user,
    )


@pytest.mark.django_db
def test_invoice_generate_add_carry_over(member, invoice_directory):
    """Tests that generating invoices multiple times for the same month + user
    will add carry-over corrections only once.
    """
    from pootle_statistics.models import Submission
    EVENT_COUNT = 5
    WORDCOUNT = 5
    TRANSLATION_RATE = 0.5
    INITIAL_SUBTOTAL = EVENT_COUNT * WORDCOUNT * TRANSLATION_RATE
    MINIMAL_PAYMENT = 20

    month = timezone.datetime(2014, 04, 01)
    config = dict({
        'minimal_payment': MINIMAL_PAYMENT,
    }, **FAKE_CONFIG)
    invoice = Invoice(member, config, month=month, add_correction=True)

    # Set some rates
    member.rate = TRANSLATION_RATE
    member.save()

    # Fake some activity that will leave amounts below the minimum bar:
    # EVENT_COUNT * WORDCOUNT * TRANSLATION_RATE < MINIMAL_PAYMENT
    for i in range(EVENT_COUNT):
        scorelog_kwargs = {
            'wordcount': WORDCOUNT,
            'similarity': 0,
            'action_code': TranslationActionCodes.NEW,
            'creation_time': month,
            'user': member,
            'submission': Submission.objects.all()[i],
        }
        ScoreLogFactory(**scorelog_kwargs)

    # Inspect numbers prior to actual generation
    amounts = invoice._calculate_amounts()
    assert amounts['subtotal'] == INITIAL_SUBTOTAL
    assert amounts['correction'] == 0
    assert amounts['total'] == INITIAL_SUBTOTAL

    assert not invoice.is_carried_over

    # Generate an invoice first
    invoice.generate()

    _check_single_paidtask(invoice, INITIAL_SUBTOTAL)
    assert PaidTask.objects.filter(task_type=PaidTaskTypes.CORRECTION).count() == 2

    # Now numbers have been adjusted
    assert invoice.amounts['balance'] == INITIAL_SUBTOTAL
    assert invoice.amounts['correction'] == INITIAL_SUBTOTAL * -1  # carry-over
    assert invoice.amounts['total'] == 0

    assert not invoice.needs_carry_over(invoice.amounts['subtotal'])
    assert invoice.is_carried_over

    # Inspecting numbers doesn't alter anything
    amounts = invoice._calculate_amounts()
    assert amounts['subtotal'] == 0
    assert amounts['correction'] == INITIAL_SUBTOTAL * -1
    assert amounts['total'] == 0

    # Subsequent invoice generations must not add any corrections
    invoice.generate()

    _check_single_paidtask(invoice, INITIAL_SUBTOTAL)
    assert PaidTask.objects.filter(task_type=PaidTaskTypes.CORRECTION).count() == 2

    assert invoice.amounts['subtotal'] == 0
    assert invoice.amounts['correction'] == INITIAL_SUBTOTAL * -1
    assert invoice.amounts['total'] == 0

    assert not invoice.needs_carry_over(invoice.amounts['subtotal'])
    assert invoice.is_carried_over


@pytest.mark.django_db
def test_invoice_generate_negative_balance(member, invoice_directory):
    """Tests that generated invoices that resulted in a negative balance (debt)
    are carried over the next month.
    """
    from pootle_statistics.models import Submission

    WORDCOUNT = 5
    TRANSLATION_RATE = 5
    WORK_DONE = WORDCOUNT * TRANSLATION_RATE
    CORRECTION = -100
    SUBTOTAL = WORK_DONE + CORRECTION

    month = timezone.datetime(2014, 04, 01)
    invoice = Invoice(member, FAKE_CONFIG, month=month, add_correction=True)

    # Set some rates
    member.rate = TRANSLATION_RATE
    member.save()

    # Work done + negative correction leaves amounts in negative
    scorelog_kwargs = {
        'wordcount': WORDCOUNT,
        'similarity': 0,
        'action_code': TranslationActionCodes.NEW,
        'creation_time': month,
        'user': member,
        'submission': Submission.objects.first(),
    }
    ScoreLogFactory(**scorelog_kwargs)

    paid_task_kwargs = {
        'amount': CORRECTION,
        'rate': 1,
        'datetime': month,
        'user': member,
        'task_type': PaidTaskTypes.CORRECTION,
    }
    PaidTaskFactory(**paid_task_kwargs)

    # Inspect numbers prior to actual generation
    amounts = invoice._calculate_amounts()
    assert amounts['subtotal'] == SUBTOTAL
    assert amounts['correction'] == CORRECTION
    assert amounts['total'] == SUBTOTAL

    assert not invoice.is_carried_over

    invoice.generate()

    _check_single_paidtask(invoice, SUBTOTAL)
    assert PaidTask.objects.filter(task_type=PaidTaskTypes.CORRECTION).count() == 3

    # Now numbers have been adjusted
    assert invoice.amounts['balance'] == SUBTOTAL
    assert invoice.amounts['correction'] == SUBTOTAL * -1  # carry-over
    assert invoice.amounts['total'] == 0

    assert not invoice.needs_carry_over(invoice.amounts['subtotal'])
    assert invoice.is_carried_over


@pytest.mark.django_db
def test_invoice_generate_balance_with_carry_over(member, invoice_directory):
    """Tests that balance is properly reported even if a carry-over already
    existed.
    """
    from pootle_statistics.models import Submission

    WORDCOUNT = 5
    TRANSLATION_RATE = 5
    WORK_DONE = WORDCOUNT * TRANSLATION_RATE
    CORRECTION = -100
    SUBTOTAL = WORK_DONE + CORRECTION
    month = timezone.datetime(2014, 04, 01)

    # Set some rates
    member.rate = TRANSLATION_RATE
    member.save()

    # Record work
    scorelog_kwargs = {
        'wordcount': WORDCOUNT,
        'similarity': 0,
        'action_code': TranslationActionCodes.NEW,
        'creation_time': month,
        'user': member,
        'submission': Submission.objects.first(),
    }
    ScoreLogFactory(**scorelog_kwargs)

    paid_task_kwargs = {
        'amount': CORRECTION,
        'rate': 1,
        'datetime': month,
        'user': member,
        'task_type': PaidTaskTypes.CORRECTION,
    }
    PaidTaskFactory(**paid_task_kwargs)

    invoice = Invoice(member, FAKE_CONFIG, month=month, add_correction=True)
    assert not invoice.is_carried_over
    invoice.generate()
    assert invoice.is_carried_over
    assert invoice.amounts['balance'] == SUBTOTAL

    invoice_copy = Invoice(member, FAKE_CONFIG, month=month, add_correction=True)
    assert invoice_copy.is_carried_over
    invoice_copy.generate()
    assert invoice_copy.is_carried_over
    assert invoice_copy.amounts['balance'] == SUBTOTAL


@pytest.mark.django_db
def test_invoice_get_amounts(member):
    """Tests accessing amounts when they haven't been calculated yet.
    """
    user = UserFactory.build()
    invoice = Invoice(user, FAKE_CONFIG)

    with pytest.raises(AssertionError):
        invoice.amounts

    invoice.generate()

    assert invoice.amounts is not None
