# HACS and hassfest requirements for a custom integration

Research note, 2026-09-02. Question: what must `blaueis-ha-midea` satisfy to be
installable as a HACS custom repository and to pass hassfest? Every claim below
is followed by the primary source it was taken from (HACS docs and source,
Home Assistant developer docs and core source, the two GitHub Action repos).
Source code was read from the `main`/`dev` branches on the day of writing.

## Summary

- HACS needs `custom_components/<one domain>/manifest.json` plus a root `hacs.json` whose only required key is `name`; add `homeassistant: "2024.10.0"` for the minimum HA version. `render_readme` is still accepted by the schema but undocumented and has no effect since HACS 2.0 (README is always used). Unknown keys make `hacs.json` invalid.
- HACS picks the version from **GitHub releases** (latest non-draft, non-prerelease tag name); a bare tag is not enough; with no releases it downloads the default branch and shows the 7-char commit. `hide_default_branch` only hides the branch in the picker.
- `manifest.json` for HACS must carry `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version`; HA itself refuses to load a custom integration without a valid `version` (AwesomeVersion) and hassfest errors on it too. `issue_tracker` is what HA prints in "create a bug report at ..." messages.
- `requirements:` entries are pip-compatible strings; `==` pins are enforced by hassfest **only for core** integrations, custom ones may use `>=`. Entries may be PyPI names or `pkg@git+https://...@ref`. HA installs them at integration load with `uv pip install --index-strategy unsafe-first-match --constraint package_constraints.txt` (into `<config>/deps` when not in a venv/container), so anything conflicting with core constraints fails; `cryptography` and `PyYAML` are already core requirements and per the docs should not be listed.
- The HACS action checks repo metadata (description, topics, issues enabled, not archived, OSI-approved license via SPDX, README present), `hacs.json` schema, `manifest.json` schema (incl. `issue_tracker`), and brand assets (`brand/icon.png` or listing in home-assistant/brands). This repo is CC0-1.0, which SPDX marks `isOsiApproved: false`, so the `license` check fails unless ignored.
- The hassfest action runs `python3 -m script.hassfest --action validate --integration-path custom_components/<domain>` from a container tracking core `dev`: manifest schema, domain = dir name, `iot_class`, `config_flow.py` present, `services.yaml` + `translations/en.json`, JSON/translation validity, requirement format (no `--requirements` install step).
- Ready-to-use workflow YAML for both actions is in section 5.

## 1. `hacs.json`

Location and keys (HACS docs, "General"):

- "The manifest file must be located in the repository root." `name` is the only required key: "The display name that will be used in the HACS UI." Optional keys: `content_in_root`, `zip_release`, `filename`, `hide_default_branch` ("Tells HACS to not offer downloading the default branch."), `country`, `homeassistant` ("The minimum required Home Assistant version."), `hacs` ("The minimum required HACS version."), `persistent_directory` (integrations only). — https://www.hacs.xyz/docs/publish/start/
- `zip_release`: "Indicates whether the content is in a zipped archive when releases are published on GitHub." Only supported for integrations, and when enabled `filename` must be set. — https://www.hacs.xyz/docs/publish/start/ ; enforced in the action: for `HacsCategory.INTEGRATION`, `zip_release` true without `filename` raises "zip_release is True, but filename is not set". — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/hacsjson.py
- `homeassistant`: the docs note that a beta minimum is written with a `b0` suffix; otherwise only official releases are accepted. — https://www.hacs.xyz/docs/publish/start/
- Schema in HACS itself (`HACS_MANIFEST_JSON_SCHEMA`): required `name` (str); optional `content_in_root`, `country`, `filename`, `hacs`, `hide_default_branch`, `homeassistant`, `persistent_directory`, `render_readme` (bool), `zip_release`; extra keys are rejected (`vol.PREVENT_EXTRA`). — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py

`render_readme`:

- Not listed in the current docs table (see the key list above). — https://www.hacs.xyz/docs/publish/start/
- Still present in the schema (above) and in the `HacsManifest` dataclass with default `False`, but nothing in the repository base class acts on it. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py
- HACS 2.0.0 breaking change: "`info.md` files are no longer rendered. Instead, the README is used". — https://github.com/hacs/integration/releases/tag/2.0.0
- Conclusion: harmless legacy key; omit it. The docs also say "Your repository needs to have a readme with information about how to use it." — https://www.hacs.xyz/docs/publish/start/

How `homeassistant` / `hacs` minimums are enforced:

- `can_download` returns `False` when `repository_manifest.homeassistant` is set, the repository has releases, and the running HA version is lower; `_ensure_download_capabilities` raises `HacsException("This version requires Home Assistant ...")` (and the same for `hacs`) at download time. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py

How `hide_default_branch` is applied:

- The flag is only forwarded to the frontend in the repository info payload (`"hide_default_branch": repository.repository_manifest.hide_default_branch`) next to `"releases": repository.data.published_tags` and `"default_branch"`. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/websocket/repository.py

Missing `hacs.json` at runtime:

- `common_validate` only parses `hacs.json` "if RepositoryFile.HACS_JSON in [x.filename for x in self.tree]"; absence is not an error when a user adds a custom repository. The HACS action, however, fails its `hacsjson` check without it. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py and https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/hacsjson.py

Proposed file for this repository:

```json
{
  "name": "Blaueis Midea AC",
  "homeassistant": "2024.10.0"
}
```

## 2. How HACS picks a version (releases, tags, default branch)

- Docs: "If the repository uses GitHub releases, the tag name from the latest release is used to set the remote version. Just publishing tags is not enough, you need to publish releases." and "If the repository does not use tags, the 7 first characters of the last commit will be used." — https://www.hacs.xyz/docs/publish/start/
- Integration docs: "It is preferred but not required to publish releases in your repository. If you publish releases in your repository, HACS will present the user with a nice selection view of the 5 latest releases together with the default branch when they are downloading or upgrading your integration. If you don't publish releases in your repository, HACS will use the files in the branch marked as default." — https://www.hacs.xyz/docs/publish/integration/
- Source: `common_update_data` fetches up to 30 releases (`prerelease=True`), skips drafts, stores the first prerelease as `data.prerelease` and the first non-prerelease `tag_name` as `data.last_version`; `published_tags` is the list of release tag names; without releases `async_set_last_commits` stores `sha[:7]`. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py
- `version_to_download()` priority: forced ref, then `selected_tag` (if it is a published tag or the default branch), then `last_version`, then `default_branch or "main"`. — same file.
- Displayed versions are the release tag or commit, not `manifest.json` `version`: `display_installed_version` uses `installed_version` or `installed_commit`; `display_available_version` uses `prerelease` (when show_beta) or `last_version` or `last_commit`; installing the default branch sets `installed_version = None`. — same file.
- Default store inclusion additionally requires "Create a new GitHub release (not just a tag, a full release) after the actions run successfully." — https://www.hacs.xyz/docs/publish/include/
- Adding a custom repository: user flow is "Custom repositories" in the HACS menu, URL + type; "Not all repositories will work in HACS, since HACS still needs the repository to have a known structure." — https://www.hacs.xyz/docs/faq/custom_repositories/
- What HACS checks at that moment (`validate_repository` for integrations): `common_validate`, then exactly one directory under `custom_components/` (else "Repository structure for <ref> is not compliant"), then `manifest.json` is fetched and `domain` must exist (`KeyError` is recorded as "Missing expected key ..."). `issue_tracker` and `version` are *not* checked here. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/integration.py ; the registration path (`async_register_repository`) adds the repository to the skip list and logs when `validate.errors` is non-empty. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/base.py

Implication: tags are useful for HA-side identification only if they are wrapped in a GitHub release; keep the release tag and `manifest.json` `version` equal by convention, because HACS shows the tag and HA logs the manifest version.

## 3. `manifest.json`: `issue_tracker`, `version`, `requirements`

### 3.1 `version`

- HA docs: "For core integrations, this should be omitted. The version of the integration is required for custom integrations. The version needs to be a valid version recognized by AwesomeVersion like CalVer or SemVer." — https://developers.home-assistant.io/docs/creating_integration_manifest
- "The `version` key is required from Home Assistant version 2021.6". — https://developers.home-assistant.io/blog/2021/01/29/custom-integration-changes
- Runtime: the loader logs "The custom integration '%s' does not have a version key in the manifest file and was blocked from loading" (and an equivalent "does not have a valid version key" message) and refuses the integration. — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/loader.py
- hassfest: `CUSTOM_INTEGRATION_MANIFEST_SCHEMA` declares `vol.Optional("version"): vol.All(str, verify_version)` (strategies CALVER, SEMVER, SIMPLEVER, BUILDVER, PEP440), but `validate_manifest` calls `validate_version` for non-core integrations, which adds the error "No 'version' key in the manifest file." when absent. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/manifest.py
- HACS: `version` is required by the HACS action's manifest schema (coerced to `AwesomeVersion`). — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py

### 3.2 `issue_tracker`

- HA docs: "The issue tracker of your integration, where users reports issues if they run into one. If this integration is being submitted for inclusion in Home Assistant, it should be omitted." — https://developers.home-assistant.io/docs/creating_integration_manifest
- Runtime use: `async_get_issue_tracker` returns the manifest value for non-built-in integrations; `async_suggest_report_issue` renders "create a bug report at {issue_tracker}" or, without one, "report it to the author of the '{domain}' custom integration". — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/loader.py
- hassfest: optional, validated as a URL (`vol.Optional("issue_tracker"): vol.Url()`). — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/manifest.py
- HACS: required. Docs: the manifest "must at least define these keys: `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, and `version`." — https://www.hacs.xyz/docs/publish/integration/ ; enforced by the action's `integration_manifest` check against `INTEGRATION_MANIFEST_JSON_SCHEMA` (required `codeowners` list, `documentation` URL, `domain`, `issue_tracker` URL, `name`, `version`; extra keys allowed). — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/integration_manifest.py and https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py

### 3.3 Other manifest rules hassfest applies to custom integrations

- `documentation` must be `https://` and must not point at the core docs base URL ("Documentation URL should point to the custom integration documentation"). — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/manifest.py
- `domain` must equal the directory name ("Domain does not match dir name"); `iot_class` is required unless the integration type is virtual ("Domain is missing an IoT Class"). — same file.
- The schema is a strict `vol.Schema` (no `extra=ALLOW_EXTRA` at the top level), so unknown manifest keys produce "Invalid manifest: extra keys not allowed ...". The custom schema additionally allows `import_executor`. — same file.
- Only one integration per repository and all files inside `custom_components/<domain>/`. — https://www.hacs.xyz/docs/publish/integration/

### 3.4 `requirements:` form and where packages may come from

- Form: "Requirements are Python libraries or modules that you would normally install using `pip` for your component." "Each entry is a `pip` compatible string", example `["pychromecast==3.2.0"]`. — https://developers.home-assistant.io/docs/creating_integration_manifest
- Pinning: hassfest's `validate_requirements_format` rejects a requirement containing a space, one that does not match `PACKAGE_REGEX = ^(?:--.+\s)?([-_,\.\w\d\[\]]+)(==|>=|<=|~=|!=|<|>|===)*(.*)$`, and, **only when `integration.core`**, one whose separator is not `==` ("Requirement ... need to be pinned"). Custom integrations may therefore use `>=`, `~=`, ranges, or no specifier. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/requirements.py
- Sources other than PyPI: the docs give the syntax `"<library>@git+https://github.com/<user>/<project>.git@<git ref>"` where the ref is "any git reference: branch, tag, commit hash." — https://developers.home-assistant.io/docs/creating_integration_manifest ; at runtime `is_installed` returns `False` for any requirement with a URL ("we cannot verify versions, so let the package manager handle it"), so such entries are handed to `uv` on every start. — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/package.py
- Index: `install_package` runs `python -m uv pip install --quiet <package> --index-strategy unsafe-first-match [--upgrade] [--constraint <file>] [--target <dir>]`; the comment says unsafe-first-match exists "for custom components which can use a different version of a package than the one we have built the wheel for". If `UV_EXTRA_INDEX_URL` is set and that host fails, HA retries without it "so PyPI can serve the package". — same file. HA's own musllinux wheel index is https://wheels.home-assistant.io/musllinux-index/ (see Gaps for where the container sets it).
- Overlap with core: "Custom integrations should only include requirements that are not required by the Core requirements.txt." — https://developers.home-assistant.io/docs/creating_integration_manifest . On core `dev` today: `cryptography==48.0.1` and `PyYAML==6.0.3` are in both `requirements.txt` and `package_constraints.txt`; `websockets>=15.0.1` is a constraint only; `jsonschema` appears in neither. — https://raw.githubusercontent.com/home-assistant/core/dev/requirements.txt and https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/package_constraints.txt . Consequence for this repo: `cryptography>=41.0` and `pyyaml>=6.0` are redundant per the docs, and `websockets>=12.0` will always resolve to 15.0.1 or newer because the constraint file is passed to every install.

### 3.5 How and when HA installs requirements

- Requirements are processed while the integration is loaded: `async_get_integration_with_requirements` "retrieves an integration with all dependencies resolved and requirements installed" and raises `RequirementsNotFound` on failure; `_async_process_integration` skips the whole step when `hass.config.skip_pip` is set. — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/requirements.py
- `pip_kwargs`: `constraints` = `homeassistant/package_constraints.txt`, `timeout` = 60 s, and `target` = `<config_dir>/deps` only when HA runs outside a virtualenv and outside Docker (otherwise packages go to site-packages). — same file.
- `async_process_requirements` filters `skip_pip_packages` ("Skipping requirement %s. This may cause issues"), computes the missing set with `is_installed`, records failures in `install_failure_history` so the same requirement is not retried until restart, and installs under a `pip_lock`. — same file.
- Docs on the target directory: "Home Assistant will try to install the requirements into the `deps` subdirectory of the Home Assistant configuration directory if you are not using a `venv` or in something like `path/to/venv/lib/python3.6/site-packages` if you are running in a virtual environment." For development, install manually with `--target ~/.homeassistant/deps` and start HA with `--skip-pip-packages <pkg>` (or `--skip-pip`) so HA does not overwrite it. — https://developers.home-assistant.io/docs/creating_integration_manifest
- `is_installed` accepts any specifier: it parses the requirement and checks `req.specifier.contains(installed_version, prereleases=True)`. — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/package.py

Practical form for the coming libraries: `"blaueis-core==X.Y.Z"` / `"blaueis-client==X.Y.Z"` on PyPI. Exact pins are not required by hassfest for custom integrations, but a pin is the only way to make the HACS release reproducible, because HA upgrades (`--upgrade`) to whatever the specifier allows on first setup.

## 4. What the HACS validation action checks

Mechanics:

- Inputs (`action.yml`): `category` (required), `ignore` (space-separated check names), `comment` (post PR comment, default `true`), `repository`, `github_token`; it runs `docker://ghcr.io/hacs/action:main`. — https://raw.githubusercontent.com/hacs/action/main/action.yml
- Docs: "A space separated list of ignored checks"; the action "uses the same code as HACS to validate a repository"; it also runs on the `hacs/default` PRs and "Checks latest release (or default branch if no releases exist)". Pin with `uses: hacs/action@v1.0.0` if desired. — https://www.hacs.xyz/docs/publish/action/
- The image is built from `hacs/integration` (`action/Dockerfile`) on every push to `main` touching `custom_components/**` or `action/**`, so `hacs/action@main` always runs the current HACS validators. — https://raw.githubusercontent.com/hacs/integration/main/.github/workflows/action-container.yml
- Ref selection in `action/action.py`: `REPOSITORY_REF` env, else the pull-request head ref, else the pushed ref (tags stripped of `refs/tags/`), else the repository default branch; it then calls `hacs.async_register_repository(repository_full_name, category, ref)` (the same structure validation as adding a custom repository) and exits 1 on failure. — https://raw.githubusercontent.com/hacs/integration/main/action/action.py
- Check names for `ignore:` are the validator module names (`slug = module.rsplit(".")[-1]`), filtered by `INPUT_IGNORE`; validators may restrict `categories`. — https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/base.py and https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/manager.py

Validators present in `custom_components/hacs/validate/` (directory listing: https://api.github.com/repos/hacs/integration/contents/custom_components/hacs/validate):

| slug | scope | what it requires | source |
|---|---|---|---|
| `archived` | all | repository not archived | https://www.hacs.xyz/docs/publish/action/ |
| `brands` | integration | `brand/icon.png` in the repo, else the domain listed under `custom` in https://brands.home-assistant.io/domains.json ; error "The repository does not provide brand assets and is not listed in the Home Assistant brands repository." | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/brands.py |
| `description` | all | GitHub repository description set | https://www.hacs.xyz/docs/publish/action/ |
| `hacsjson` | all | `hacs.json` exists and matches the schema; integrations with `zip_release` need `filename` | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/hacsjson.py |
| `images` | plugin, theme only | README contains images | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/images.py |
| `information` | all | a `readme`, `readme.md`, `info` or `info.md` file (case-insensitive) | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/information.py |
| `integration_manifest` | integration | `manifest.json` exists ("The repository has no 'manifest.json' file") and matches `INTEGRATION_MANIFEST_JSON_SCHEMA` (codeowners, documentation, domain, issue_tracker, name, version) | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/integration_manifest.py |
| `issues` | all | GitHub issues enabled | https://www.hacs.xyz/docs/publish/action/ |
| `license` | all | GitHub-detected license with an SPDX id that is `isOsiApproved` in the SPDX list; errors "The repository has no license", "... missing an SPDX ID", "... could not be identified (SPDX: NOASSERTION)", "The repository does not have an OSI-approved license (detected: '<id>')" | https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/license.py |
| `topics` | all | repository topics set | https://www.hacs.xyz/docs/publish/action/ |

Notes on the `license` check:

- Merged into HACS on 2026-07-04 ("Add license validation for repositories", hacs/integration PR 5343); the documentation PR (hacs/documentation 687, "Document license check requirement for repository publishing") was still open at the time of writing, so the docs page above lists only eight checks. — https://github.com/hacs/integration/pull/5343 and https://github.com/hacs/documentation/pull/687
- The SPDX list marks `CC0-1.0` as `"isOsiApproved": false` (`MIT`, `Apache-2.0` are `true`). — https://raw.githubusercontent.com/spdx/license-list-data/main/json/licenses.json
- This repository's `LICENSE` is "CC0 1.0 Universal" (`LICENSE` at the repository root), so the action fails on `license` unless `ignore: license` is passed. Ignoring is technically supported for a custom repository, but default-store inclusion states the action "must pass without any errors or ignores". — https://www.hacs.xyz/docs/publish/include/

Default-store inclusion (not needed for a custom repository, listed for completeness): public GitHub repo, HACS action and hassfest passing, a full GitHub release, brands, description/topics/issues, submitter is owner or major contributor. — https://www.hacs.xyz/docs/publish/include/

## 5. What the hassfest action checks, and the CI snippets

Mechanics:

- The action is composite: it registers a problem matcher and runs `docker run --rm -v ${{ github.workspace }}://github/workspace ghcr.io/home-assistant/hassfest` with no extra arguments; there are no inputs. — https://raw.githubusercontent.com/home-assistant/actions/master/hassfest/action.yml
- The container entrypoint finds `custom_components/*/manifest.json` (depth 2, or a root-level manifest), exits 1 if none, and runs `python3 -m script.hassfest --action validate --integration-path <dir>... "$@"`. Because no `--requirements` flag is passed, requirement checking is format-only. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/docker/entrypoint.sh
- The image is `python:3.14-alpine` with core `requirements.txt`, `pipdeptree`, `tqdm`, `ruff`, entrypoint above; it tracks core `dev`, which is why the docs recommend the nightly cron ("check against the latest requirements"). — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/docker/Dockerfile and https://developers.home-assistant.io/blog/2020/04/16/hassfest
- With `--integration-path`, only `INTEGRATION_PLUGINS` run (`HASS_PLUGINS` are excluded; `generate` is refused): application_credentials, bluetooth, codeowners, conditions, config_schema, dependencies, dhcp, icons, integration_info, integration_type, json, labs, manifest, mqtt, quality_scale, requirements, services, ssdp, translations, triggers, usb, zeroconf, config_flow. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/__main__.py

What the relevant plugins do for a custom integration:

- `manifest`: schema (section 3.3), `validate_version`, domain/dir match, `iot_class`. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/manifest.py
- `requirements`: `validate_requirements_format` only (no install). — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/requirements.py
- `config_flow`: `config_flow.py` must exist when `config_flow: true`; missing unique-id handling in discovery steps is a warning for specific integrations. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/config_flow.py
- `codeowners`: returns early for specific integrations; no `CODEOWNERS` file needed. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/codeowners.py
- `dependencies`: only "Using component {domain} but it's not in 'dependencies' or 'after_dependencies'" (import scan); existence/circularity checks are skipped. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/dependencies.py
- `translations`: parses `strings.json` and, for specific integrations, `translations/en.json` against the schema ("Invalid JSON in ...", "Invalid ..."); missing files are skipped, reference checks are skipped. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/translations.py
- `services`: `services.yaml` must parse and match `CUSTOM_INTEGRATION_SERVICES_SCHEMA`; service and field names/descriptions are looked up in `translations/en.json` ("Service {name} has no name in the translations file", "... has a field {field} with no name ..."); "Registers services but has no services.yaml" if `async_register` is found without the file. — https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/services.py

Workflow YAML. The HACS action needs no checkout (it reads the repository through the GitHub API); hassfest needs one. Both upstream examples use the nightly cron.

```yaml
# .github/workflows/validate.yml
name: Validate

on:
  push:
  pull_request:
  schedule:
    - cron: "0 0 * * *"
  workflow_dispatch:

permissions: {}

jobs:
  hacs:
    runs-on: ubuntu-latest
    steps:
      - name: HACS validation
        uses: hacs/action@main
        with:
          category: integration
          # ignore: license   # only while the CC0 question in section 4 is open

  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: home-assistant/actions/hassfest@master
```

Upstream references for the two job bodies: https://www.hacs.xyz/docs/publish/action/ (HACS, `permissions: {}`, `category: "CHANGE_ME!"`) and https://github.com/home-assistant/actions (hassfest, `actions/checkout@v4` + `home-assistant/actions/hassfest@master`). The existing `ci.yml` (lint + pytest) stays as is; this is a separate workflow so the nightly cron does not rerun the test suite.

## 6. Applied to this repository

Observed state (files at the repository root): `manifest.json` has `version` `0.1.0`, `config_flow`, `codeowners`, `documentation`, `iot_class`, four `>=` requirements, no `issue_tracker`; no `hacs.json`; no `brand/` directory; `LICENSE` is CC0-1.0; `strings.json`, `translations/en.json` and `services.yaml` exist; one local tag, no releases; `.github/workflows/ci.yml` only.

To be installable as a custom repository (runtime checks only): already satisfied (one directory under `custom_components/`, `manifest.json` with `domain`, valid `version`). Adding `hacs.json` with `name` + `homeassistant` is still needed for the HACS action and to enforce the 2024.10 minimum.

To pass the HACS action: add `hacs.json`; add `"issue_tracker": "https://github.com/fabcoded/blaueis-ha-midea/issues"`; add `brand/icon.png`; set the GitHub description and topics and keep issues enabled; decide on the license (`ignore: license` or relicense to an OSI-approved license).

To pass hassfest: expected to pass on the manifest today; `services.yaml` entries must have `name`/`description` for every service and field in `translations/en.json`; requirements must stay space-free and regex-conformant (the current `>=` entries are fine). Per the HA docs, drop `cryptography` and `pyyaml` from `requirements` (core requirements) unless there is a reason to override; add the PyPI pins for `blaueis-core`/`blaueis-client` when published.

For version selection: publish a GitHub release (not only a tag) whose tag matches `manifest.json` `version`; leave `hide_default_branch` unset until the first release exists.

## Gaps / open points

- Where the HA container sets `UV_EXTRA_INDEX_URL` was not located in a primary source: the core `Dockerfile` sets only `S6_SERVICES_GRACETIME`, `UV_SYSTEM_PYTHON`, `UV_NO_CACHE` (https://raw.githubusercontent.com/home-assistant/core/dev/Dockerfile), and the base-image and s6 `run` scripts fetched show no such line. `package.py` honours the variable when present, and the index at https://wheels.home-assistant.io/musllinux-index/ exists; treat the "container adds the HA wheels index" statement as unverified.
- HACS docs lag the code: the action docs list eight checks and omit `integration_manifest` and `license`; `render_readme` is undocumented but still schema-valid. Re-check https://www.hacs.xyz/docs/publish/action/ after hacs/documentation PR 687 merges.
- No code was found in HACS that compares the release tag with `manifest.json` `version`; equality is a convention, not a rule.
- The exact validation applied to the `homeassistant` value format (beyond the docs' `b0` note and the AwesomeVersion comparison in `base.py`) was not traced further.
- hassfest's `icons`, `json`, `integration_info`, `integration_type`, `labs`, `quality_scale` plugins were not read in detail; they are listed as running for custom integrations but their custom-specific branches were not verified.
- The HA docs still show `==` pins in their example; whether HA maintainers *recommend* pins for custom integrations (beyond hassfest not requiring them) is a judgement, not a documented rule.

## Sources

HACS documentation
- https://www.hacs.xyz/docs/publish/start/ — hacs.json keys, README requirement, releases vs tags vs commit
- https://www.hacs.xyz/docs/publish/integration/ — repository structure, mandatory manifest keys, brand assets, releases
- https://www.hacs.xyz/docs/publish/include/ — default-store checks and prerequisites
- https://www.hacs.xyz/docs/publish/action/ — action YAML, inputs, documented checks
- https://www.hacs.xyz/docs/faq/custom_repositories/ — adding a custom repository

HACS source (hacs/integration, `main`)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/integration.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/base.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/websocket/repository.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/base.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/manager.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/brands.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/hacsjson.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/images.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/information.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/integration_manifest.py
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/license.py
- https://raw.githubusercontent.com/hacs/integration/main/action/action.py
- https://raw.githubusercontent.com/hacs/integration/main/.github/workflows/action-container.yml
- https://github.com/hacs/integration/releases/tag/2.0.0
- https://github.com/hacs/integration/pull/5343 and https://github.com/hacs/documentation/pull/687

HACS action
- https://raw.githubusercontent.com/hacs/action/main/action.yml

Home Assistant developer documentation
- https://developers.home-assistant.io/docs/creating_integration_manifest — version, issue_tracker, requirements, custom requirements during development
- https://developers.home-assistant.io/blog/2021/01/29/custom-integration-changes — version required from 2021.6
- https://developers.home-assistant.io/blog/2020/04/16/hassfest — hassfest action introduction and YAML

Home Assistant actions and core source (`master` / `dev`)
- https://github.com/home-assistant/actions — hassfest README and YAML
- https://raw.githubusercontent.com/home-assistant/actions/master/hassfest/action.yml
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/docker/entrypoint.sh
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/docker/Dockerfile
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/__main__.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/manifest.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/requirements.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/config_flow.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/codeowners.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/dependencies.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/translations.py
- https://raw.githubusercontent.com/home-assistant/core/dev/script/hassfest/services.py
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/loader.py
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/requirements.py
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/package.py
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/package_constraints.txt
- https://raw.githubusercontent.com/home-assistant/core/dev/requirements.txt
- https://raw.githubusercontent.com/home-assistant/core/dev/Dockerfile

Other
- https://raw.githubusercontent.com/spdx/license-list-data/main/json/licenses.json — `isOsiApproved` flags
- https://brands.home-assistant.io/domains.json — brands fallback list used by the HACS action
