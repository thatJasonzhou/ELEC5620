"""Local Financial MVP. Run: streamlit run ui/financial_ui.py."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.demo.financial_app import FinancialDemoApp
from src.financial_config import deposit_rate


def money(cents):
    sign = '-' if cents < 0 else ''
    value = abs(cents)
    return f'{sign}AUD {value // 100:,}.{value % 100:02d}'


@st.cache_resource
def demo_app(path):
    return FinancialDemoApp(path)


def act(key, label, call, *, disabled=False):
    if st.button(label, key=key, disabled=disabled):
        st.session_state['financial_result'] = call()
        st.rerun()


def main():
    st.set_page_config(page_title='Financial Demo', layout='wide')
    st.title('Financial Demo')
    st.caption('MOCK payments & supplier replies · Planning STUB · Operations STUB')
    st.info('A local, single-operator demonstration. Financial checks cover the saved mock settlement scope. '
            'Event closure is handled separately by Operations.')
    import os
    path = str(Path(os.environ.get('ELEC5620_DB_PATH') or ROOT / 'runtime/financial-demo.sqlite3').resolve())
    try:
        app = demo_app(path)
        events = app.contexts.list_events()
    except Exception:
        st.error('Demo storage unavailable. Check the database configuration; no automatic reset was performed.')
        st.stop()

    with st.sidebar:
        st.subheader('Saved demonstrations')
        if st.button('Create new demo', key='create_demo'):
            result = app.create_demo()
            st.session_state['financial_result'] = result
            if result['status'] == 'success':
                st.session_state['financial_event'] = result['data']['event_id']
            st.rerun()
        if not events:
            st.info('Create a demo to begin. No approval or payment is created automatically.')
            st.stop()
        if st.session_state.get('financial_event') not in events:
            st.session_state['financial_event'] = events[0]
        event = st.selectbox('Activity', events, key='financial_event')
        st.caption('Catering · Melbourne · 5 December 2026 · 120 guests')
        st.caption('After a payment request is created, inputs are frozen. Create a new demo to change them.')

    loaded = app.load_demo(event)
    history_result = app.get_history(event)
    if loaded['status'] != 'success' or history_result['status'] != 'success':
        st.error('Unable to read the complete activity. Manual review required.')
        st.stop()
    ctx, history = loaded['data'], history_result['data']
    result = st.session_state.get('financial_result')
    if result and result.get('event_id') in (None, event):
        renderer = {'success': st.success, 'blocked': st.warning, 'needs_input': st.warning, 'error': st.error}
        renderer.get(result['status'], st.info)(result['message'])
        with st.expander('Last operation details'):
            st.json(result)

    policy_valid = True
    try:
        rate = deposit_rate()
        st.caption(f'Configured deposit rate: {rate * 100}% · Payments are simulated only.')
    except ValueError as exc:
        policy_valid = False
        st.error(str(exc))

    deposits = history['deposits']
    finals = history['final_payments']
    frozen = bool(deposits or finals)
    quotes = [q for q in ctx['quotations'] if q.get('available') is True]

    st.subheader('1. Activity and supplier quotation')
    act('request_quotes', 'Request mock quotations', lambda: app.request_quotations(event), disabled=frozen)
    if quotes:
        st.dataframe([dict(Vendor=q['vendor_id'], Quotation=q['quotation_id'],
                           Service=q['service_type'], Amount=money(q['quoted_total_cents'])) for q in quotes],
                     hide_index=True, use_container_width=True)
        ids = [q['quotation_id'] for q in quotes]
        with st.form('selection_' + event):
            selected = st.selectbox('Supplier quotation', ids, disabled=frozen)
            budget_dollars = st.number_input('Budget limit (AUD)', min_value=1,
                value=max(1, ctx['event']['budget_limit_cents'] // 100), step=100, disabled=frozen)
            if st.form_submit_button('Save selection and budget', disabled=frozen):
                st.session_state['financial_result'] = app.update_selection(
                    event, [selected], budget_dollars * 100, ctx['revision'])
                st.rerun()
    else:
        st.caption('Request quotations before selecting a supplier.')

    st.subheader('2. Budget and customer quotation')
    act('budget', 'Calculate budget', lambda: app.prepare_budget(event), disabled=not ctx['selected_quotation_ids'])
    budget = ctx['budget']
    if budget:
        st.dataframe([{'Item': label, 'Amount': money(budget[key])} for label, key in (
            ('Supplier cost', 'vendor_total_cents'), ('Company service fee', 'service_fee_cents'),
            ('Contingency', 'contingency_cents'), ('Customer total', 'estimated_total_cents'))],
            hide_index=True, use_container_width=True)
        st.caption('GST-inclusive amounts; no separate tax breakdown.')
        if not budget['within_budget']:
            st.warning('Over budget by ' + money(budget['over_budget_cents']))
    act('quote', 'Generate customer quotation', lambda: app.generate_customer_quotation(event),
        disabled=not budget or not budget['within_budget'])
    quote = ctx['customer_quotation']
    if quote:
        st.write('Customer quotation: ' + quote['customer_quotation_id'])
        st.metric('Quoted customer total', money(quote['estimated_total_cents']))

    st.subheader('3. Customer approval and deposit')
    st.caption('Approval is an explicit demo customer action bound to this quotation.')
    act('approve', 'Approve current quotation (mock customer)',
        lambda: app.approve_customer_quotation(event, quote['customer_quotation_id'], ctx['revision']),
        disabled=not quote or bool(ctx['approval']))
    st.write('Customer approval: ' + ('Confirmed for current quotation' if ctx['approval'] else 'Required'))
    act('prepare_deposit', 'Prepare deposit request', lambda: app.prepare_deposit(event),
        disabled=not ctx['approval'] or not policy_valid)
    if deposits:
        saved = deposits[-1]
        d = saved['deposit']
        st.write(f"Deposit: {money(d['amount_cents'])} · {d['status']} · {saved['execution_state']}")
        act('pay_deposit', 'Simulate deposit payment',
            lambda: app.pay_deposit(event, d['deposit_request_id'], d['amount_cents']),
            disabled=not policy_valid or d['status'] != 'pending' or saved['execution_state'] != 'not_started')
        if saved['execution_state'] in ('execution_started', 'requires_reconciliation'):
            st.error('Deposit outcome uncertain. Manual reconciliation required; do not pay again.')

    st.subheader('4. Supplier booking')
    act('book', 'Confirm mock supplier booking', lambda: app.confirm_bookings(event),
        disabled=not any(r['deposit']['status'] == 'paid' for r in deposits))
    try:
        bookings = app.procurement_records.get_bookings(event, ctx['proposal_id'])
    except Exception:
        st.error('Supplier booking storage unavailable. Manual review required.')
        st.stop()
    if bookings:
        st.dataframe([{'Booking': b['booking_id'], 'Vendor': b['vendor_id'], 'Status': b['status']}
                      for b in bookings], hide_index=True, use_container_width=True)

    st.subheader('5. Final collection and supplier settlement')
    balance = app.get_customer_balance(event) if ctx['approval'] else None
    if balance and balance['status'] == 'success':
        st.metric('Customer balance', money(balance['data']['balance']['balance_cents']))
    elif balance:
        st.warning(balance['message'])
    act('prepare_final', 'Prepare final payment request', lambda: app.prepare_final(event),
        disabled=not policy_valid or not ctx['approval'] or not bookings)
    for saved in finals:
        f = saved['payment']
        st.write(f"Final payment: {money(f['amount_cents'])} · {f['status']} · {saved['execution_state']}")
        act('pay_final_' + f['final_request_id'], 'Simulate final payment',
            lambda f=f: app.pay_final(event, f['final_request_id'], f['amount_cents']),
            disabled=not policy_valid or f['status'] != 'pending' or saved['execution_state'] != 'prepared')
        if saved['execution_state'] in ('executing', 'requires_reconciliation'):
            st.error('Final payment outcome uncertain. Manual reconciliation required; do not pay again.')

    st.warning('Operations STUB: generating evidence simulates completed service, including when the event date '
               'is in the future. It does not prove actual service completion.')
    act('operations', 'Generate mock invoice and completion evidence',
        lambda: app.create_operations_stub(event), disabled=not bookings)
    try:
        evidence = app.operations.get(event)
    except Exception:
        st.error('Settlement scope changed or evidence unavailable. Manual review required.')
        st.stop()
    if evidence:
        with st.expander('Operations STUB scope and evidence'):
            st.json(evidence)
    for b in bookings:
        st.write('Supplier settlement for ' + b['booking_id'])
        act('prepare_vendor_' + b['booking_id'], 'Prepare supplier payment',
            lambda b=b: app.prepare_vendor_payment(event, b['booking_id']), disabled=not evidence or not policy_valid)
    for payment in history['vendor_payments']:
        st.write(f"Supplier payment: {money(payment['amount_cents'])} · {payment['status']}")
        uncertain = payment['status'] == 'pending' and payment['payment_id'] in ctx.get('vendor_execution_attempts', {})
        if uncertain:
            st.error('Supplier payment was attempted but has no saved terminal outcome. Manual review required; do not retry.')
        act('pay_vendor_' + payment['payment_id'], 'Simulate supplier payment',
            lambda p=payment: app.pay_vendor(event, p['payment_id'], p['amount_cents']),
            disabled=not policy_valid or payment['status'] != 'pending' or not evidence or uncertain)

    st.subheader('6. Saved financial records and read-only check')
    act('reconcile', 'Run financial check (mock scope)', lambda: app.reconcile(event))
    if result and result.get('event_id') == event and 'financial_check_passed' in result['data']:
        if result['data']['financial_check_passed']:
            st.success('Financial check passed within the saved mock settlement scope.')
        else:
            st.warning('Financial check has not passed. Review outstanding balances and evidence.')
        st.json(result['data'])
    with st.expander('Saved financial history'):
        st.json(history)


if __name__ == '__main__':
    main()
