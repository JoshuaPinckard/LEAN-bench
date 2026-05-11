"""Concrete provider clients. Each module is imported on demand so missing
SDKs only fail when actually used (e.g. you can run smoke_test against
Anthropic without having google-genai installed)."""
