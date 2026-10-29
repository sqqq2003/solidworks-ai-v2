"""Provider-neutral design discussion; native execution remains outside chat."""
from .client import AIConfig,AssistantError,ResponsesClient
from .session import AssistantSession
__all__=['AIConfig','AssistantError','ResponsesClient','AssistantSession','ModelClient']

# Stable alias for integrations that are no longer OpenAI-specific.
ModelClient=ResponsesClient
