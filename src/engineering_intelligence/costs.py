"""Source/dated quotation estimates; unknown amounts never become zero totals."""
from datetime import date
from .common import quantity, number, index, result


def estimate_cost(request):
    lines=[]; pending=[]; subtotal=0.
    currency=request['currency']
    if not isinstance(currency,str) or len(currency)!=3: raise ValueError('explicit currency code required')
    as_of=date.fromisoformat(request['as_of']); index(request['items'])
    for item in request['items']:
        if item['kind'] not in {'material','process','standard_part'}: raise ValueError('invalid cost item kind')
        amount=quantity(item['quantity'],item['quantity_unit'],minimum=0)
        loss=quantity(item['loss'],'ratio',minimum=0)
        if loss>=1: raise ValueError('loss fraction must be below one')
        quote=item.get('quote'); known=True
        if not quote:
            pending.append('missing_price:'+item['id']);known=False
        else:
            if quote.get('currency')!=currency or quote.get('per_unit')!=item['quantity_unit']:
                raise ValueError('quote currency/unit mismatch; no implicit FX conversion')
            price=number(quote['value'],minimum=0)
            if not quote.get('source') or not quote.get('date'): pending.append('missing_quote_provenance:'+item['id']);known=False
            else:
                quoted=date.fromisoformat(quote['date'])
                if quoted>as_of: pending.append('quote_after_estimate_date:'+item['id']);known=False
                if quote.get('valid_until') and date.fromisoformat(quote['valid_until'])<as_of:
                    pending.append('quote_expired:'+item['id']);known=False
        extended=amount/(1-loss)*price if known else None
        if extended is not None: subtotal+=extended
        lines.append({'id':item['id'],'kind':item['kind'],'net_quantity':amount,'gross_quantity':amount/(1-loss),
                      'unit':item['quantity_unit'],'extended_cost':extended,'quote':quote})
    if not lines: pending.append('empty_cost_items')
    return result({'currency':currency,'as_of':request['as_of'],'lines':lines,'known_subtotal':subtotal,
                   'total':None if pending else subtotal,'exclusions':request.get('exclusions',[]),
                   'scope':'budget estimate only; tax/freight/labour must be explicit line items or exclusions'},issues=pending)
