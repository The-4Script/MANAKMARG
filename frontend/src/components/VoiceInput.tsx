import { Loader2, Mic, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { useI18n } from "../i18n/I18nProvider";
import { cx } from "./ui";

export type VoiceLanguage = "auto" | "en" | "hi";
type Phase = "idle" | "recording" | "processing" | "error";

const MAX_SECONDS = 30;
const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return PREFERRED_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

function extensionFor(type: string): string {
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4")) return "m4a";
  return "webm";
}

/** Records a spoken question and returns the transcript; the caller asks it through the normal assistant flow. */
export default function VoiceInput({ enabled, disabled, onTranscript }: { enabled: boolean; disabled?: boolean; onTranscript: (text: string, language: VoiceLanguage) => void }) {
  const { t, lang } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<VoiceLanguage>(lang === "hi" ? "hi" : "auto");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | null>(null);
  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const releaseMicrophone = () => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  };

  useEffect(() => releaseMicrophone, []);

  const stop = () => {
    if (recorder.current?.state === "recording") recorder.current.stop();
  };

  const send = async (blob: Blob, mimeType: string) => {
    setPhase("processing");
    const form = new FormData();
    form.append("file", blob, `voice.${extensionFor(mimeType)}`);
    form.append("language", language);
    try {
      const result = await api.upload<{ text: string }>("/voice/transcribe", form);
      setPhase("idle");
      onTranscript(result.text, language);
    } catch (reason) {
      setPhase("error");
      setError(reason instanceof ApiError ? reason.message : t("voice.failed"));
    }
  };

  const start = async () => {
    setError(null);
    const mimeType = pickMimeType();
    try {
      // Explicit constraints (rather than a bare `audio: true`) so noisy phones and laptop mics still get a clean
      // signal to transcribe: cutting echo/background noise and normalising volume measurably improves Whisper's
      // accuracy, since a mis-heard word downstream can't be fixed no matter how good the transcription model is.
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      stream.current = media;
      const next = new MediaRecorder(media, mimeType ? { mimeType, audioBitsPerSecond: 128_000 } : { audioBitsPerSecond: 128_000 });
      chunks.current = [];
      next.ondataavailable = (event) => {
        if (event.data.size) chunks.current.push(event.data);
      };
      next.onstop = () => {
        const type = next.mimeType || mimeType || "audio/webm";
        releaseMicrophone();
        const blob = new Blob(chunks.current, { type });
        if (blob.size < 1024) {
          setPhase("error");
          setError(t("voice.tooShort"));
          return;
        }
        void send(blob, type);
      };
      recorder.current = next;
      next.start();
      setSeconds(0);
      setPhase("recording");
      timer.current = window.setInterval(() => {
        setSeconds((value) => {
          if (value + 1 >= MAX_SECONDS) stop();
          return value + 1;
        });
      }, 1000);
    } catch {
      releaseMicrophone();
      setPhase("error");
      setError(t("voice.permission"));
    }
  };

  const unavailable = !enabled ? t("voice.unavailable") : !supported ? t("voice.unsupported") : null;
  const busy = phase === "recording" || phase === "processing";

  return (
    <>
      <div className="flex items-center gap-1.5">
        <label className="sr-only" htmlFor="voice-language">
          {t("voice.language")}
        </label>
        <select
          id="voice-language"
          value={language}
          onChange={(event) => setLanguage(event.target.value as VoiceLanguage)}
          disabled={busy || !!unavailable}
          className="hidden rounded-lg border border-slate-200 bg-white px-1.5 py-2 text-xs text-slate-700 disabled:opacity-50 sm:block"
          title={t("voice.language")}
        >
          <option value="auto">{t("voice.auto")}</option>
          <option value="en">English</option>
          <option value="hi">हिंदी</option>
        </select>
        {phase === "recording" ? (
          <button type="button" onClick={stop} className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-700" aria-label={t("voice.stop")}>
            <Square className="size-4 fill-current" aria-hidden />
            <span className="tabular-nums">0:{String(seconds).padStart(2, "0")}</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void start()}
            disabled={disabled || phase === "processing" || !!unavailable}
            title={unavailable ?? t("voice.start")}
            aria-label={unavailable ?? t("voice.start")}
            className={cx(
              "inline-flex items-center justify-center rounded-xl border px-3 py-2 text-ink-800 hover:border-ink-600 disabled:cursor-not-allowed disabled:opacity-50",
              phase === "processing" ? "border-ink-200 bg-ink-50" : "border-slate-200 bg-white",
            )}
          >
            {phase === "processing" ? <Loader2 className="size-5 animate-spin" aria-hidden /> : <Mic className="size-5" aria-hidden />}
          </button>
        )}
      </div>
      {(phase === "recording" || phase === "processing" || phase === "error") && (
        <p role="status" aria-live="polite" className={cx("basis-full px-2 text-sm", phase === "error" ? "text-rose-700" : "text-slate-600")}>
          {phase === "recording" && (
            <span className="inline-flex items-center gap-2">
              <span className="size-2 animate-pulse rounded-full bg-rose-600" aria-hidden />
              {t("voice.listening", { seconds: MAX_SECONDS })}
            </span>
          )}
          {phase === "processing" && t("voice.processing")}
          {phase === "error" && (
            <span className="inline-flex flex-wrap items-center gap-2">
              {error}
              <button type="button" onClick={() => void start()} className="inline-flex items-center gap-1 font-medium text-ink-700 hover:underline">
                <RotateCcw className="size-3.5" aria-hidden /> {t("voice.retry")}
              </button>
            </span>
          )}
        </p>
      )}
    </>
  );
}
