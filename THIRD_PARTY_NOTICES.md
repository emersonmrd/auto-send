# Third-party notices

Auto-Send is licensed under the MIT License (see `LICENSE`). The Windows portable package also
redistributes the third-party software listed below, each under its own license. Their copyright
notices and license texts belong to their authors; this file points to them.

## Bundled programs (Windows portable package)

These run as separate processes. Auto-Send does not link to them, so their licenses do not apply
to Auto-Send's own code.

| Component | Version | License | Source |
|---|---|---|---|
| FFmpeg (`ffmpeg.exe`, `ffprobe.exe`), "essentials" build by Gyan Doshi | 7.1 | GPL-3.0-or-later (build includes GPL components) | https://ffmpeg.org/download.html#get-sources · build: https://github.com/GyanD/codexffmpeg/releases/tag/7.1 |
| telegram-bot-api (`telegram-bot-api.exe`) | 10.3 | BSL-1.0 | https://github.com/tdlib/telegram-bot-api · build: https://github.com/SwissCore92/telegram-bot-api-bin |
| OpenSSL (`libcrypto-3-x64.dll`, `libssl-3-x64.dll`) | 3.x | Apache-2.0 | https://www.openssl.org/source/ |
| zlib (`z.dll`) | 1.x | Zlib | https://zlib.net/ |
| Microsoft Visual C++ Redistributable runtime DLLs | 14.x | Microsoft Visual C++ Redistributable license terms | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |
| Python embeddable package | 3.12 | PSF-2.0 | https://www.python.org/downloads/source/ |

**FFmpeg source offer:** the FFmpeg binaries are unmodified builds. The complete corresponding
source code is available at the links above; the build's own `LICENSE` and `README` list the
exact libraries and configuration used.

## Python runtime dependencies (backend)

| Package | License |
|---|---|
| aiofiles | Apache-2.0 |
| aiogram, magic-filter | MIT |
| aiohappyeyeballs | PSF-2.0 |
| aiohttp | Apache-2.0 AND MIT |
| aiosignal, frozenlist, multidict, propcache, yarl | Apache-2.0 |
| aiosqlite | MIT |
| annotated-doc, annotated-types, anyio, attrs, h11, pydantic, pydantic-core, typing-inspection | MIT |
| APScheduler, tzlocal | MIT |
| certifi | MPL-2.0 |
| click, httpcore, httpx, idna, starlette, uvicorn | BSD-3-Clause |
| fastapi | MIT |
| greenlet | MIT AND PSF-2.0 |
| opentelemetry-api | Apache-2.0 |
| python-multipart | Apache-2.0 |
| SQLAlchemy | MIT |
| typing-extensions | PSF-2.0 |
| tzdata | Apache-2.0 |

## JavaScript runtime dependencies (frontend bundle)

| Package | License |
|---|---|
| next, react, react-dom (and their bundled helpers `scheduler`, `styled-jsx`) | MIT |
| `@swc/helpers` | Apache-2.0 |
| lucide-react | ISC |

Build-time and development tools (test runners, linters, bundlers, image optimizers) are not
redistributed and are not listed here.
