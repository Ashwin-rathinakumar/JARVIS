"""One utterance per COM-owning process; no assistant or STT initialization."""
import json
import sys


def speak_once(payload, engine_factory=None):
    if engine_factory is None:
        import pyttsx3
        engine_factory = pyttsx3.init
    engine = engine_factory()
    outcomes = []
    errors = []
    engine.connect("finished-utterance", lambda name, completed: outcomes.append((name, completed)))
    engine.connect("error", lambda name, exception: errors.append(str(exception)))
    try:
        engine.setProperty("rate", payload["rate"])
        engine.setProperty("volume", payload["volume"])
        engine.say(payload["text"], "response")
        engine.runAndWait()
        if ("response", True) not in outcomes or errors:
            raise RuntimeError("Speech did not complete: " + "; ".join(errors))
    finally:
        engine.stop()


if __name__ == "__main__":
    try:
        speak_once(json.load(sys.stdin))
        print("TTS_COMPLETED", flush=True)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
