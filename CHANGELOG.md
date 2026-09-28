# CHANGELOG

<!-- version list -->

## v0.8.1 (2026-09-28)

### Bug Fixes

- **ci**: Wait for Backplane SSH before deployment
  ([#108](https://github.com/worganisation/backplane/pull/108),
  [`1662ed3`](https://github.com/worganisation/backplane/commit/1662ed39e395ad987bb3b468c96efa21bc6fc972))

### Chores

- **deps**: Update tailscale/github-action action to v4.2.0
  ([#109](https://github.com/worganisation/backplane/pull/109),
  [`90dc0ac`](https://github.com/worganisation/backplane/commit/90dc0ac66c82355589f3e49bb242a07a1e017bbd))


## v0.8.0 (2026-09-27)

### Bug Fixes

- Keep atomic vault writes on the destination filesystem
  ([#105](https://github.com/worganisation/backplane/pull/105),
  [`af98e85`](https://github.com/worganisation/backplane/commit/af98e85d8774cd4ad383e9006697c1bfa0957f0a))

- **ci**: Use the GCF deploy-key release workflow
  ([#106](https://github.com/worganisation/backplane/pull/106),
  [`26e70d9`](https://github.com/worganisation/backplane/commit/26e70d9388af8fa74579ddbe2a2dcbb0854af176))

### Chores

- Use uv for Dependabot updates ([#73](https://github.com/worganisation/backplane/pull/73),
  [`09fc0f3`](https://github.com/worganisation/backplane/commit/09fc0f3c5aee21100acfe6e1d00b92a589e6807a))

- 🔄 synced file(s) with worganisation/github-config-files
  ([#107](https://github.com/worganisation/backplane/pull/107),
  [`4978888`](https://github.com/worganisation/backplane/commit/4978888bfe04c10115aa09acd468cb80de71b771))

- **ci**: Align workflows with GCF ([#76](https://github.com/worganisation/backplane/pull/76),
  [`f0930a7`](https://github.com/worganisation/backplane/commit/f0930a75aeac4479ef34473d31f91ba5c30a94b8))

- **deps**: Bump aiohttp from 3.14.1 to 3.14.3
  ([#71](https://github.com/worganisation/backplane/pull/71),
  [`0dde22c`](https://github.com/worganisation/backplane/commit/0dde22c28f0402b3021b4c454720b4b7ab158ee2))

- **deps**: Bump anyio from 4.13.0 to 4.14.2
  ([#100](https://github.com/worganisation/backplane/pull/100),
  [`8735a41`](https://github.com/worganisation/backplane/commit/8735a41d4514f8318ada9f91ab9ae68fa4f72bfd))

- **deps**: Bump cryptography from 48.0.1 to 50.0.0
  ([#72](https://github.com/worganisation/backplane/pull/72),
  [`6ec7ff6`](https://github.com/worganisation/backplane/commit/6ec7ff6089552c2de69d21f10eea9be5c4706584))

- **deps**: Bump pydantic-ai from 1.102.0 to 1.106.0
  ([#74](https://github.com/worganisation/backplane/pull/74),
  [`c8493b6`](https://github.com/worganisation/backplane/commit/c8493b653d4a4e55e7d341da037c1d06de3732cd))

- **deps**: Bump python-semantic-release/python-semantic-release from 10.6.1 to 10.6.2
  ([#79](https://github.com/worganisation/backplane/pull/79),
  [`30cc9e7`](https://github.com/worganisation/backplane/commit/30cc9e7e60439204d7b06468e5e5b93d6328e576))

- **deps**: Bump tailscale/github-action from 4.1.2 to 4.1.3
  ([#81](https://github.com/worganisation/backplane/pull/81),
  [`5a12f27`](https://github.com/worganisation/backplane/commit/5a12f272388ece51679d5e6b375ed800e585b714))

- **deps**: Bump the uv-dependencies group with 7 updates
  ([#101](https://github.com/worganisation/backplane/pull/101),
  [`58b4af0`](https://github.com/worganisation/backplane/commit/58b4af0ce1377a274398d49c34999d746ad593d8))

- **deps**: Configure Renovate updates ([#102](https://github.com/worganisation/backplane/pull/102),
  [`945db88`](https://github.com/worganisation/backplane/commit/945db8885981d44299592e171e58ec96e6aa397b))

- **deps**: Update fastmcp requirement from >=3.3.1 to >=3.4.7
  ([#82](https://github.com/worganisation/backplane/pull/82),
  [`ba89bdf`](https://github.com/worganisation/backplane/commit/ba89bdfa074d260c60ec4d64d1b3c44c02e3f30f))

- **deps**: Update pydantic requirement from >=2.10 to >=2.13.5
  ([#89](https://github.com/worganisation/backplane/pull/89),
  [`ee4b235`](https://github.com/worganisation/backplane/commit/ee4b235f4cb0202f075aebdb45ccb7fd6324d6c1))

- **deps**: Update pydantic-ai requirement from >=1.106.0 to >=2.36.0
  ([#92](https://github.com/worganisation/backplane/pull/92),
  [`b0d0867`](https://github.com/worganisation/backplane/commit/b0d08670313a396a5686da3092aa188213c8a660))

- **deps**: Update pydantic-settings requirement from >=2.14.2 to >=2.15.0
  ([#83](https://github.com/worganisation/backplane/pull/83),
  [`bfdcaf2`](https://github.com/worganisation/backplane/commit/bfdcaf27b0802fb6a830f9dcb9801fee99f3c0bb))

- **deps**: Update rapidfuzz requirement from >=3.0 to >=3.14.5
  ([#91](https://github.com/worganisation/backplane/pull/91),
  [`702e52c`](https://github.com/worganisation/backplane/commit/702e52c25609f95c94383c2597cc863c54b65905))

- **deps**: Update uvicorn requirement from >=0.46.0 to >=0.52.4
  ([#86](https://github.com/worganisation/backplane/pull/86),
  [`f7d0bcd`](https://github.com/worganisation/backplane/commit/f7d0bcddb791e1ad5053ef6e1dd9b38e9aad66b1))

- **deps-dev**: Update basedpyright requirement from >=1.39.7 to >=1.39.10
  ([#84](https://github.com/worganisation/backplane/pull/84),
  [`12e6f29`](https://github.com/worganisation/backplane/commit/12e6f29263ce9585ad9f8bc90dad94ad8e11cc30))

- **deps-dev**: Update diff-cover requirement from >=10.2.0 to >=10.5.1
  ([#90](https://github.com/worganisation/backplane/pull/90),
  [`dc6f027`](https://github.com/worganisation/backplane/commit/dc6f02716ff2437aa76118b16199a8df6a62b871))

- **deps-dev**: Update pytest requirement from >=8.0 to >=9.1.1
  ([#88](https://github.com/worganisation/backplane/pull/88),
  [`6d2d229`](https://github.com/worganisation/backplane/commit/6d2d229e03f199cb68a67b06d1382a176bf0cd9c))

- **deps-dev**: Update pytest-asyncio requirement from >=0.25 to >=1.4.0
  ([#93](https://github.com/worganisation/backplane/pull/93),
  [`6c55c39`](https://github.com/worganisation/backplane/commit/6c55c39dd56cef7ae0fbac31b3fc11130a938981))

- **deps-dev**: Update pytest-cov requirement from >=7.0.0 to >=7.1.0
  ([#80](https://github.com/worganisation/backplane/pull/80),
  [`13df629`](https://github.com/worganisation/backplane/commit/13df6299725674701f12d4a3b15c60bb4574114a))

- **deps-dev**: Update pytest-env requirement from >=1.2.0 to >=1.7.0
  ([#87](https://github.com/worganisation/backplane/pull/87),
  [`ad3e9b5`](https://github.com/worganisation/backplane/commit/ad3e9b573dc486f212e308177c48896acb3a2bb9))

- **deps-dev**: Update pytest-mock requirement from >=3.14 to >=3.15.1
  ([#85](https://github.com/worganisation/backplane/pull/85),
  [`8ca98b0`](https://github.com/worganisation/backplane/commit/8ca98b0e4f3b809de40e24cf4ae882f42852959b))

- **sync**: Pin github-config-files workflows to 0.8.6
  ([#78](https://github.com/worganisation/backplane/pull/78),
  [`96f7846`](https://github.com/worganisation/backplane/commit/96f784691e3240ca39c6bf847d20091a061f2102))

- **sync**: Pin github-config-files workflows to 0.8.7
  ([#99](https://github.com/worganisation/backplane/pull/99),
  [`b1264d3`](https://github.com/worganisation/backplane/commit/b1264d3105d2c9f592b24059f1533dff90b6609a))

### Features

- Add REST API for vault operations ([#70](https://github.com/worganisation/backplane/pull/70),
  [`2233bcb`](https://github.com/worganisation/backplane/commit/2233bcb2a29b8d7dbb75a4d299eeec579f938253))

- Enhance MCP OAuth client registration ([#69](https://github.com/worganisation/backplane/pull/69),
  [`db4aa27`](https://github.com/worganisation/backplane/commit/db4aa277aad58aaabf31ff6ec066eb1d5b69c04a))

- **ci**: Deploy published releases after manual release creation
  ([#103](https://github.com/worganisation/backplane/pull/103),
  [`ccd5ab9`](https://github.com/worganisation/backplane/commit/ccd5ab99b5f39b441982b57e0ac786c244667a8f))


## v0.7.0 (2026-07-26)

### Bug Fixes

- Update OAuth scopes and streamline HA MCP proxy
  ([#68](https://github.com/worgarside/backplane/pull/68),
  [`de4d8e1`](https://github.com/worgarside/backplane/commit/de4d8e11594f5d98380cd19991c75058b5e4a34c))

### Chores

- **deps**: Bump joserfc from 1.6.5 to 1.6.7
  ([#59](https://github.com/worgarside/backplane/pull/59),
  [`607b7d7`](https://github.com/worgarside/backplane/commit/607b7d768f4805c744e92f5fe8bb89c149ebbc2d))

- **deps**: Bump joserfc from 1.6.7 to 1.6.8
  ([#64](https://github.com/worgarside/backplane/pull/64),
  [`b0989b4`](https://github.com/worgarside/backplane/commit/b0989b49251397045dd72a0123afac84171b7d21))

- **deps**: Bump mcp from 1.27.1 to 1.28.1 ([#65](https://github.com/worgarside/backplane/pull/65),
  [`a50ce5c`](https://github.com/worgarside/backplane/commit/a50ce5ce1af4a3821a14ce3f40a85532c466501d))

- **deps**: Bump pyasn1 from 0.6.3 to 0.6.4 ([#67](https://github.com/worgarside/backplane/pull/67),
  [`99ade49`](https://github.com/worgarside/backplane/commit/99ade49da693c2a57ebe8372c568dc897fd033e0))

- **deps**: Bump pydantic-ai from 1.99.0 to 1.102.0
  ([#60](https://github.com/worgarside/backplane/pull/60),
  [`ddba8f2`](https://github.com/worgarside/backplane/commit/ddba8f26fb312a7f3d7ef78d726dbc1b1dd762d6))

- **deps**: Bump pydantic-ai-slim from 1.99.0 to 1.102.0
  ([#61](https://github.com/worgarside/backplane/pull/61),
  [`451028f`](https://github.com/worgarside/backplane/commit/451028f8a911e880f00fd879ec9865909e767836))

- **deps**: Bump pydantic-settings from 2.14.1 to 2.14.2
  ([#57](https://github.com/worgarside/backplane/pull/57),
  [`5fadcb3`](https://github.com/worgarside/backplane/commit/5fadcb37ba59301fa12703cb8978d20fd7414d03))

### Code Style

- Fixes from prek hooks
  ([`d3f616d`](https://github.com/worgarside/backplane/commit/d3f616d7affe8ac9f83ddf5eee1a31fafcc1bdee))

### Continuous Integration

- Prek autoupdate ([#66](https://github.com/worgarside/backplane/pull/66),
  [`1d6f480`](https://github.com/worgarside/backplane/commit/1d6f4808fc8a83d01bd0334e901b0ed5aa351904))

- Prek autoupdate ([#63](https://github.com/worgarside/backplane/pull/63),
  [`d3beda8`](https://github.com/worgarside/backplane/commit/d3beda883d1568802649cefecca0c8762923fbbb))

- Prek autoupdate ([#58](https://github.com/worgarside/backplane/pull/58),
  [`33d58d9`](https://github.com/worgarside/backplane/commit/33d58d9d8e8e432fd70a21bc6c3b314861c8002b))

### Features

- Enable HA MCP proxy through Backplane ([#62](https://github.com/worgarside/backplane/pull/62),
  [`10343da`](https://github.com/worgarside/backplane/commit/10343da8b93a6a0d247d8c9dfd9f99610496a165))


## v0.6.0 (2026-06-22)

### Code Style

- Fixes from prek hooks
  ([`32b34c7`](https://github.com/worgarside/backplane/commit/32b34c79b6b3b0d107711523102634dded10e1cb))

### Continuous Integration

- Prek autoupdate ([#56](https://github.com/worgarside/backplane/pull/56),
  [`e98964e`](https://github.com/worgarside/backplane/commit/e98964eddec4d9ff061abc02eb7e7196c786ff5e))

### Features

- Enhance note search capabilities ([#55](https://github.com/worgarside/backplane/pull/55),
  [`b557e5b`](https://github.com/worgarside/backplane/commit/b557e5b9834d2507ff7be383bf19ffb82dca1a6e))


## v0.5.0 (2026-06-16)

### Chores

- **deps**: Bump aiohttp from 3.13.5 to 3.14.0
  ([#37](https://github.com/worgarside/backplane/pull/37),
  [`812e58f`](https://github.com/worgarside/backplane/commit/812e58f321c3033da60328c17144c487195ac3ae))

- **deps**: Bump aiohttp from 3.14.0 to 3.14.1
  ([#53](https://github.com/worgarside/backplane/pull/53),
  [`7013dd4`](https://github.com/worgarside/backplane/commit/7013dd43beb3e3e5ac83ff8ab37f5b46cb00ef6e))

- **deps**: Bump cryptography from 48.0.0 to 48.0.1
  ([#51](https://github.com/worgarside/backplane/pull/51),
  [`8a4a1e6`](https://github.com/worgarside/backplane/commit/8a4a1e6ff604645de7502b789d70f5855fa30bfc))

- **deps**: Bump pyjwt from 2.12.1 to 2.13.0
  ([#47](https://github.com/worgarside/backplane/pull/47),
  [`dc6e9b7`](https://github.com/worgarside/backplane/commit/dc6e9b7552a5b06a4f32eb9285869fa1e48626ae))

- **deps**: Bump python-multipart from 0.0.28 to 0.0.31
  ([#52](https://github.com/worgarside/backplane/pull/52),
  [`6fe5c67`](https://github.com/worgarside/backplane/commit/6fe5c67047d66edef1517e694cb811cd8bd12763))

- **deps**: Bump starlette from 1.0.0 to 1.0.1
  ([#38](https://github.com/worgarside/backplane/pull/38),
  [`cbfc46f`](https://github.com/worgarside/backplane/commit/cbfc46f0de89e8d10ebfbc8959005c13e1b38e86))

- **deps**: Bump starlette from 1.0.1 to 1.3.1
  ([#54](https://github.com/worgarside/backplane/pull/54),
  [`aa37097`](https://github.com/worgarside/backplane/commit/aa37097f63424e637a236818af50dd09261f0256))

### Continuous Integration

- Enforce coverage checks at 90% ([#41](https://github.com/worgarside/backplane/pull/41),
  [`3b1d3b5`](https://github.com/worgarside/backplane/commit/3b1d3b5cf11a1a49e86c05ee4b0db37cae392a3c))

- Prek autoupdate ([#45](https://github.com/worgarside/backplane/pull/45),
  [`34313b3`](https://github.com/worgarside/backplane/commit/34313b3f0cbecadfe68aca3da145455eae7f2079))

- Prek autoupdate ([#42](https://github.com/worgarside/backplane/pull/42),
  [`4efbeba`](https://github.com/worgarside/backplane/commit/4efbeba1abc258771b2bf3a7af6b2efafd10aa77))

- Prek autoupdate ([#39](https://github.com/worgarside/backplane/pull/39),
  [`3af1be7`](https://github.com/worgarside/backplane/commit/3af1be794f158e220bf0f4f2c9815e8f80ca63f5))

- Prek autoupdate ([#36](https://github.com/worgarside/backplane/pull/36),
  [`0e494c8`](https://github.com/worgarside/backplane/commit/0e494c8012a39106b92910b423b12fdf8898f893))

### Features

- Add public ChatGPT MCP server with Authentik OAuth
  ([#35](https://github.com/worgarside/backplane/pull/35),
  [`0d06652`](https://github.com/worgarside/backplane/commit/0d06652a9bc2ac97d73dbdbfe875ac2f14ff6c8a))

- Auto-generate README MCP catalog section ([#44](https://github.com/worgarside/backplane/pull/44),
  [`2e79faf`](https://github.com/worgarside/backplane/commit/2e79faf117abeff7524e977ad6ec3659d6abe0ba))

- Integrate vault entity management tools ([#43](https://github.com/worgarside/backplane/pull/43),
  [`a07e53d`](https://github.com/worgarside/backplane/commit/a07e53df8641a0fbcee219bae64607359f6feaa9))

### Refactoring

- Move scripts to deploy folder ([#46](https://github.com/worgarside/backplane/pull/46),
  [`f2fea9a`](https://github.com/worgarside/backplane/commit/f2fea9a0c7ebd9d2c2f4f3aeacc9faadf9808dad))


## v0.4.3 (2026-05-30)

### Bug Fixes

- **tasks**: Prevent task creation from blocking on ambiguous capture matches
  ([#31](https://github.com/worgarside/backplane/pull/31),
  [`31c3c09`](https://github.com/worgarside/backplane/commit/31c3c098b55fcd638982bea1c7b8b9526d42ea04))

### Continuous Integration

- Prek autoupdate ([#30](https://github.com/worgarside/backplane/pull/30),
  [`267f9eb`](https://github.com/worgarside/backplane/commit/267f9eb3a33619cda3e486cf4bd6ef69ae7090ee))


## v0.4.2 (2026-05-30)

### Bug Fixes

- Use git reset to ensure clean deploys ([#33](https://github.com/worgarside/backplane/pull/33),
  [`e6b1fa8`](https://github.com/worgarside/backplane/commit/e6b1fa82bd406c53608a94c6144f6f1a6334d896))


## v0.4.1 (2026-05-30)

### Refactoring

- Update log directory handling ([#32](https://github.com/worgarside/backplane/pull/32),
  [`c6115eb`](https://github.com/worgarside/backplane/commit/c6115ebfdc276a3b8f26809716757d002594ed26))


## v0.4.0 (2026-05-27)

### Bug Fixes

- Use explicit LOCAL_TIMEZONE setting instead of system timezone
  ([#19](https://github.com/worgarside/backplane/pull/19),
  [`d23c7f8`](https://github.com/worgarside/backplane/commit/d23c7f87cee001d47a17b94a6828797bd2c9e97e))

### Chores

- **deps**: Bump idna from 3.13 to 3.15 ([#22](https://github.com/worgarside/backplane/pull/22),
  [`4032f19`](https://github.com/worgarside/backplane/commit/4032f19dfd33c5ffeae3494b8e7ea9122cc2bf0d))

- **deps**: Bump pydantic-ai from 1.97.0 to 1.99.0
  ([#26](https://github.com/worgarside/backplane/pull/26),
  [`e02a867`](https://github.com/worgarside/backplane/commit/e02a867de29f0c42970961f768b10651bf753a4d))

### Code Style

- Fixes from prek hooks
  ([`7c447d2`](https://github.com/worgarside/backplane/commit/7c447d2fd0067689271473eb5c52d7c28ff8456f))

### Continuous Integration

- Prek autoupdate ([#29](https://github.com/worgarside/backplane/pull/29),
  [`a564d74`](https://github.com/worgarside/backplane/commit/a564d74cd17bd300dca39c47821f248c74b247a2))

- Prek autoupdate ([#20](https://github.com/worgarside/backplane/pull/20),
  [`790d264`](https://github.com/worgarside/backplane/commit/790d2646b2882209491828ed44566ce205b2462f))

### Features

- Add due dates to Kanban cards ([#23](https://github.com/worgarside/backplane/pull/23),
  [`b5c4454`](https://github.com/worgarside/backplane/commit/b5c44546112bcfb12060ac1c443bced1df721c7e))

- Add helper utilities ([#21](https://github.com/worgarside/backplane/pull/21),
  [`2c5514b`](https://github.com/worgarside/backplane/commit/2c5514b2113bb549f7cdd0c6ced023ce79c4e5e4))

- Dynamic startup notification title ([#18](https://github.com/worgarside/backplane/pull/18),
  [`0c0deda`](https://github.com/worgarside/backplane/commit/0c0dedac8ab112394ca8080b15b70f21978bf096))

- Introduce custom exception handling ([#25](https://github.com/worgarside/backplane/pull/25),
  [`bbd5d4c`](https://github.com/worgarside/backplane/commit/bbd5d4c5c8064fb86216ed16d07daddd80b25a4d))

- Support task creation from voice input ([#28](https://github.com/worgarside/backplane/pull/28),
  [`95041ba`](https://github.com/worgarside/backplane/commit/95041ba1d424148ac03bcd42a12e822df18c8983))

### Refactoring

- Use atomic writes for markdown files ([#24](https://github.com/worgarside/backplane/pull/24),
  [`bff7ac9`](https://github.com/worgarside/backplane/commit/bff7ac929f1d1a1d027df19ad30ff825ae15381b))


## v0.3.0 (2026-05-17)

### Chores

- Add logging for server and obsidian functions
  ([#16](https://github.com/worgarside/backplane/pull/16),
  [`25c0cb8`](https://github.com/worgarside/backplane/commit/25c0cb8f3792f44fa6cd37b972bcf481cf3ba5e3))

### Features

- Integrate Home Assistant for MCP auto-reload
  ([#15](https://github.com/worgarside/backplane/pull/15),
  [`b6f6206`](https://github.com/worgarside/backplane/commit/b6f62061fca260748ad9fb6d7d4dc137a5d7a683))

### Performance Improvements

- Enhance event loop with uvloop ([#17](https://github.com/worgarside/backplane/pull/17),
  [`d33f88f`](https://github.com/worgarside/backplane/commit/d33f88fb22bd9efd6268245f2202e3b065a08243))


## v0.2.1 (2026-05-17)

### Continuous Integration

- Add build command for package updates ([#14](https://github.com/worgarside/backplane/pull/14),
  [`d54f4a7`](https://github.com/worgarside/backplane/commit/d54f4a7733b711ebe45d3c8a06e7137ea41494ce))

- Change deploy env ([#13](https://github.com/worgarside/backplane/pull/13),
  [`b0e3df8`](https://github.com/worgarside/backplane/commit/b0e3df81a3266b462652df65286bd3a49ba22bec))


## v0.2.0 (2026-05-17)

### Bug Fixes

- Replace UTC timezone with local timezone ([#9](https://github.com/worgarside/backplane/pull/9),
  [`1b1ddfa`](https://github.com/worgarside/backplane/commit/1b1ddfa0e7ca272178ca0df8da3a7abfb5056be4))

### Continuous Integration

- Add automated deployment step to CI workflow
  ([#11](https://github.com/worgarside/backplane/pull/11),
  [`258669c`](https://github.com/worgarside/backplane/commit/258669c2a00f39790e627bcb3a8882bbebb6cea8))

- Exclude init file from release triggers ([#6](https://github.com/worgarside/backplane/pull/6),
  [`c9372d5`](https://github.com/worgarside/backplane/commit/c9372d5b22ef8973772a8cf0c98de302c1f9f81d))

- Exclude main branch from PR workflow ([#12](https://github.com/worgarside/backplane/pull/12),
  [`5d48531`](https://github.com/worgarside/backplane/commit/5d48531b7e558b076a7bccb3bdc6e12c395929f9))

- Prek autoupdate ([#8](https://github.com/worgarside/backplane/pull/8),
  [`e376591`](https://github.com/worgarside/backplane/commit/e3765914a04c911a6f4bdce5947056857c8f3479))

### Features

- Add idea recording to Obsidian ([#7](https://github.com/worgarside/backplane/pull/7),
  [`aa5ca9d`](https://github.com/worgarside/backplane/commit/aa5ca9dca26d4a0817f5ab003ae0be0cfeb7c09b))


## v0.1.0 (2026-05-16)

- Initial Release
