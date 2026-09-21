# Third-party material and distribution scope

Original project code has no project-wide license selected in this repository.
This preparation does not assign one on behalf of its owner. Upstream files
retain their own notices and terms; the vendored license does not license the
whole project.

| Material | Location / provenance |
| --- | --- |
| docker_open5gs configuration and init sources | [Provenance](app/infrastructure/vendor/docker_open5gs/PROVENANCE.md), [upstream license](app/infrastructure/vendor/docker_open5gs/LICENSE) |
| STT package and model | [Model provenance](app/services/ai-worker/MODEL_PROVENANCE.md), service requirements and Dockerfile |
| Qwen GGUF and optional model alternatives | URL and SHA-256 in `app/config/lab.env`; [model guide](docs/local-models.md) |
| Piper engine and RU/EN voice models | Pinned downloads in the Voice Agent build and public configuration; [voice guide](docs/configuration.md) |
| Infrastructure images and Python dependencies | Image references in `app/config/lab.env`, Dockerfiles and `requirements*.txt` |

Model weights and container images are downloaded during setup, not embedded in
the source repository. Their licenses and redistribution obligations are separate
from the source code. Review the exact upstream notices before redistributing
built images or weights. This inventory is not a license clearance report.
