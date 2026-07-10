# Third-Party Notices

Jarvis Line's core Python package has no required third-party runtime
dependencies. Optional integrations and development tools remain governed by
their own upstream licenses.

## Kokoro

- [`kokoro-onnx`](https://github.com/thewh1teagle/kokoro-onnx) is an optional
  local inference package published under the MIT License.
- The pinned `kokoro-v1.0.onnx` and `voices-v1.0.bin` assets are obtained from
  the upstream [`model-files-v1.0` release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
  The upstream project identifies the model as Apache-2.0 licensed.
- Jarvis Line does not bundle those model assets in its Python package or macOS
  app. The explicit download command shows the source and license, then verifies
  pinned file size and SHA-256 values before installation.

## Other Optional Tools

Key Kokoro playback dependencies, system speech tools, custom TTS providers,
and development/test packages are listed in [docs/TTS.md](docs/TTS.md). Jarvis Line
does not grant rights to third-party services, voices, models, or content; users
must follow the license and usage terms of the components they choose.

Release automation uses the Apache-2.0 licensed
[`anchore/sbom-action`](https://github.com/anchore/sbom-action) and Syft to
generate an SPDX JSON bill of materials from the artifacts built at the release
tag. These tools are used in GitHub Actions and are not installed by Jarvis Line
at runtime.
