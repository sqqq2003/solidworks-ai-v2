"""Explicit domain adapters over existing solid and sheet implementations.

A sheet plan is never treated as a solid feature list. The caller of a native
sheet adapter must supply its already-owned STA/WindowsSheetMetalPort; the
legacy sheet pipeline's own staging/reopen/DXF recovery stays authoritative.
"""
from copy import deepcopy


class ModelingAdapter:
    domain = 'modeling'

    def capabilities(self):
        from modeling_domain import capabilities
        return capabilities()

    def analyze(self, plan, **kwargs):
        from modeling_domain import analyze_draft
        return analyze_draft(plan, **kwargs)

    def run_transaction(self, plan, port, **kwargs):
        from modeling_domain import run_transaction
        return run_transaction(plan, port, **kwargs)

    def run_native(self, plan, *args, **kwargs):
        from modeling_domain.api import run_native_modeling
        return run_native_modeling(plan, *args, **kwargs)


class SheetMetalAdapter:
    domain = 'sheet_metal'

    def capabilities(self):
        return {'domain': self.domain, 'contract_version': 1,
                'operations': ['base_flange', 'sketched_bends', 'reopen_inspect', 'flat_dxf'],
                'implementation': 'sheet_metal_pipeline + WindowsSheetMetalPort',
                'recovery': 'existing_staged_sheet_pipeline',
                'solid_transaction_contract': False, 'manufacturing_approved': False}

    def analyze(self, analysis, **kwargs):
        from sheet_metal_pipeline import build_plan
        return {'domain': self.domain, 'contract_version': 1, 'plan': build_plan(analysis, **kwargs)}

    def run_transaction(self, contract, analysis, output_dir, port, **kwargs):
        from sheet_metal_pipeline import run_plan
        if contract.get('domain') != self.domain or contract.get('contract_version') != 1:
            raise ValueError('explicit sheet_metal contract version 1 required')
        result = deepcopy(run_plan(analysis, contract['plan'], output_dir, port, **kwargs))
        return {**result, 'domain': self.domain, 'delivery_accepted': False,
                'manufacturing_approved': False}


def get_adapter(domain):
    if domain == 'modeling':
        return ModelingAdapter()
    if domain == 'sheet_metal':
        return SheetMetalAdapter()
    raise ValueError('unsupported CAD domain: ' + str(domain))
