# Blaueis Midea integration

Home Assistant custom integration for Midea air conditioners reached through a Blaueis gateway. This glossary holds the terms the project uses when talking about the integration's releases and its install experience; protocol and field vocabulary lives in the glossary YAML.

## Language

### Release

**Stranger test**:
The bar a release must clear: a Home Assistant user with a Raspberry Pi and a Midea AC, who has never spoken to us, gets a working climate entity following only the public READMEs — hardware prerequisites, gateway install, integration install via HACS custom repository, configuration. The 0.1.0 finish line.
_Avoid_: finish line (workspace-tracker shorthand for the same thing), release readiness

**Publication** (two levels):
*GitHub publication* is the repositories becoming public on GitHub; *package publication* is the library on PyPI and the integration installable through HACS — what 0.1.0 delivers. "Post-publication" in older notes means after the first level.
_Avoid_: "published" without naming the level

**Release-cut gate**:
The technical readiness condition for a release — the deployed gateway and integration are stable on the same protocol version. Distinct from the Stranger test: the gate can be satisfied while a stranger still cannot install.
_Avoid_: release gate, publish gate
