# ADR 0004: Pluggable LLM Provider Architecture and Data Governance

## Status
Accepted · 2026-11-08

## Context
A production RAG service deployed across educational institutions must satisfy strict data governance, cost, and deployment flexibility constraints:
1. **Model Mobility:** Developers may run lightweight local models during local development (e.g., `ollama` with `llama3.2:3b`), while production or staging environments may leverage high-throughput hosted inference endpoints (e.g., Groq, Google AI Studio, or OpenAI-compatible gateways) without requiring code modifications.
2. **CI Isolation (No Model / No Network):** Automated testing suites and GitHub Actions CI pipelines must execute deterministically without relying on external API availability, network access, or expensive token consumption.
3. **Data Governance and PII Protection:** Student academic inquiries, grades, and policy concerns constitute sensitive information. Model keys must never be committed to source control or exposed in container image layers. Retrieved document content must be treated strictly as untrusted data rather than system instructions.

## Decision
We enforce a pluggable `LLMProvider` interface selected via the `LLM_PROVIDER` environment variable:
1. **Interface Contract:**
   All providers implement a common Python protocol:
   ```python
   class LLMProvider(Protocol):
       name: str
       def generate(self, question: str, passages: list[Passage]) -> Answer: ...
   ```
2. **Provider Implementations:**
   - `StubProvider`: Deterministic, zero-network mock returning fixture answers and citations for CI and offline unit testing.
   - `OllamaProvider`: Connects to `ollama-host` (`http://host.minikube.internal:11434`) or `ollama-incluster` with schema-enforced JSON generation (`format="json"`).
   - `HostedProvider`: Connects to OpenAI-compatible hosted endpoints with response format schema constraints.
3. **Data Governance & Security Rules:**
   - **Secret Isolation:** `LLM_API_KEY` is injected exclusively via Kubernetes Secrets (`rahbar-secret`), never stored in ConfigMaps, Dockerfiles, or Git repositories.
   - **Data-Instruction Separation:** In the augmented prompt, retrieved passage texts are encapsulated within strict `<evidence>` delimiters and explicitly identified as reference data. Instructions instruct the model to ignore any imperative commands embedded inside the retrieved texts.
   - **Output Schema Validation:** All model outputs must be validated by Pydantic against the `Answer` schema. Parsing failures trigger a single retry followed by a safe canned fallback, preventing 500 server errors or arbitrary code execution.

## Options Considered
1. **Direct Coupling to a Single Cloud SDK (e.g. OpenAI SDK only):** Violates portability requirements and makes offline CI impossible without paid accounts.
2. **Heavyweight Orchestration Frameworks (e.g. LangChain):** Introduces excessive dependency bloat, version drift, and opaque abstraction layers.
3. **Pluggable Protocol with Built-in Stubs (Chosen):** Clean single-file swaps, zero external dependencies for offline test runs, and complete architectural transparency.

## Consequences
- **Positive:** Tests run offline in < 2 seconds with `pytest` and 100% determinism.
- **Positive:** Zero risk of secret leakage or prompt injection escaping schema constraints.
- **Trade-off:** Each provider must implement response formatting to guarantee compliance with the `Answer` Pydantic model.
