# Security policy

ModelLab is research software for one trusted operator on their own machine. It's not a production security control.

**Report a vulnerability** by opening a GitHub issue that asks for a private contact, with no technical details in it. Sandbox escapes, redaction failures, and authentication bypasses are especially useful.

**Run it safely**
- Keep the API and dashboard on loopback, which is the default. Don't expose them to a network.
- Treat traces as sensitive, even though credentials are redacted.
- Use only synthetic data in scenarios. Never add real credentials or customer data.

**Acceptable use:** test only systems you own or are explicitly authorized to test. The attack generator targets the local sandbox, and there's no feature for targeting external systems.

See [docs/threat-model.md](docs/threat-model.md) and [docs/limitations.md](docs/limitations.md).
