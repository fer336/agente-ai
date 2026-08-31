"""Tiny, real, mutagen-parseable audio byte blobs for tests that exercise
duration probing (`TranscribeAudioUseCase._probe_duration_seconds`).

A hand-rolled fake byte string (e.g. `b"fake-audio-bytes"`) cannot stand in
here — `mutagen.File()` needs a genuinely valid container to report a
duration at all, and a duration-validation test needs a REAL positive
duration to compare against a configured limit. Generated once via:

    ffmpeg -f lavfi -i "anullsrc=r=8000:cl=mono" -t 0.1 -c:a libopus short.ogg

then base64-inlined here so no test depends on `ffmpeg` being installed.
"""

import base64

#: A valid, silent, ~0.1 second Ogg Opus file (WhatsApp's real voice-note
#: container format, PRD.md §68's `AUDIO_ALLOWED_MIME_TYPES` includes
#: `audio/ogg`).
TINY_VALID_OGG_BYTES = base64.b64decode(
    "T2dnUwACAAAAAAAAAADZ5mdpAAAAAP1L2/4BE09wdXNIZWFkAQE4AUAfAAAAAABPZ2dTAAAAAAAA"
    "AAAAANnmZ2kBAAAAye3j1QE8T3B1c1RhZ3MMAAAATGF2ZjYzLjEuMTAxAQAAABwAAABlbmNvZGVy"
    "PUxhdmM2My4xLjEwMSBsaWJvcHVzT2dnUwAE+BMAAAAAAADZ5mdpAgAAAH/AtXIGAwMDAwMDmP/+"
    "mP/+mP/+mP/+mP/+mP/+"
)

#: This file's actual duration in seconds (per `mutagen`), for assertions.
TINY_VALID_OGG_DURATION_SECONDS = 0.1
