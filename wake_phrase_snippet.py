def wait_for_wake_phrase(
    keywords: tuple[str, ...] = WAKE_PHRASE_KEYWORDS,
    *,
    timeout: float | None = None,
    recognizer_factory=None,
    microphone_factory=None,
) -> bool:
    """Hold startup until the wake phrase (e.g. 'Jarvis, activate') is heard."""
    if os.environ.get("JARVIS_SKIP_WAKE_GATE", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[JARVIS] Startup wake-phrase gate bypassed (JARVIS_SKIP_WAKE_GATE).")
        return True

    try:
        import speech_recognition as sr
    except ImportError:
        print("[JARVIS] Startup wake-phrase gate needs SpeechRecognition. Set JARVIS_SKIP_WAKE_GATE=1 to bypass.")
        return False

    recognizer = (recognizer_factory or sr.Recognizer)()
    microphone_factory = microphone_factory or sr.Microphone

    print("[JARVIS] Waiting for you to say \"Jarvis, activate\"...")
    started_at = time.monotonic()

    try:
        with microphone_factory() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            while True:
                if timeout is not None and time.monotonic() - started_at >= timeout:
                    print("[JARVIS] Startup wake-phrase gate timed out.")
                    return False
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=WAKE_PHRASE_LISTEN_SECONDS,
                        phrase_time_limit=WAKE_PHRASE_PHRASE_TIME_LIMIT,
                    )
                except sr.WaitTimeoutError:
                    continue
                try:
                    transcript = recognizer.recognize_google(audio).strip().lower()
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as exc:
                    print(f"[JARVIS] Wake-phrase recognition service unavailable: {exc}")
                    if os.environ.get("JARVIS_REQUIRE_WAKE_GATE", "").strip().lower() not in {"1", "true", "yes", "on"}:
                        print("[JARVIS] Continuing without the wake-phrase gate; recognition service is unavailable.")
                        return True
                    return False
                if transcript:
                    print(f"[JARVIS] Heard: \"{transcript}\"")
                if all(keyword in transcript for keyword in keywords):
                    print("[JARVIS] Wake phrase detected. Powering up...")
                    return True
    except KeyboardInterrupt:
        print("\n[JARVIS] Startup cancelled.")
        return False
    except Exception as exc:
        print(f"[JARVIS] Startup wake-phrase microphone unavailable: {exc}")
        if os.environ.get("JARVIS_REQUIRE_WAKE_GATE", "").strip().lower() not in {"1", "true", "yes", "on"}:
            print("[JARVIS] Continuing without the wake-phrase gate; microphone input is unavailable.")
            print("[JARVIS] Restore microphone access to use voice activation.")
            return True
        print("[JARVIS] Wake-phrase gate required. Set JARVIS_SKIP_WAKE_GATE=1 to bypass it.")
        return False