"""Review existing design plans; never creates a CAD session or authorizes writes."""
from .impact import analyze_impact,review_digest,record_approval
from .acceptance import evaluate_acceptance
from .repair import propose_repairs
__all__=['analyze_impact','review_digest','record_approval','evaluate_acceptance','propose_repairs']
