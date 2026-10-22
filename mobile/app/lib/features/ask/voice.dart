import 'dart:async';

import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Why listening failed: the microphone is not allowed or not there, or the recogniser failed (its service,
/// its network, the audio). Silence is not a failure: the turn simply ends with no words.
enum VoiceError { microphone, recognition }

/// Speaking to the assistant and hearing its answer, with the phone's own speech recognition and
/// voice: nothing is recorded or sent but the words recognised, which go as the typed question
/// would. Tests replace it.
abstract class Voice {
  /// Whether the device can listen (a recogniser, and the microphone allowed). Asks once.
  Future<bool> canListen();

  /// Listen until the person pauses: [onWords] gets the words as they are recognised, with `last` true once
  /// (with no words when nothing was said). [onLevel] gets the input level (0–1) when the device reports it;
  /// [onError] says why listening failed, after which `last` is not called. Returns when listening has started.
  Future<void> listen(void Function(String words, bool last) onWords,
      {void Function(double level)? onLevel, void Function(VoiceError error)? onError});

  Future<void> stopListening();

  /// Read [text] aloud; completes when it has been said, or [quiet] was called. [onWord] is called as each word
  /// is spoken, where the device reports it.
  Future<void> speak(String text, {void Function()? onWord});

  Future<void> quiet();

  /// How fast to speak: 1 is the device's normal pace, less is slower.
  Future<void> setRate(double rate);

  /// Whether the person can be heard while the phone speaks (to interrupt it by voice). The phone's own
  /// recogniser cannot: Android gives the audio to the voice while it speaks, and it would hear the phone itself.
  bool get canListenWhileSpeaking;
}

class DeviceVoice implements Voice {
  final _speech = SpeechToText();
  final _tts = FlutterTts();
  bool? _ready;
  void Function(String, bool)? _onWords;
  void Function(VoiceError)? _onError;
  void Function(double)? _onLevel;
  void Function()? _onWord;
  String _heard = '';

  @override
  bool get canListenWhileSpeaking => false;

  @override
  Future<bool> canListen() async {
    _ready ??= await _speech.initialize(
      onError: _failed,
      // "done" also comes when nothing was heard: the listener is still told it is over.
      onStatus: (s) {
        if (s == SpeechToText.doneStatus || s == SpeechToText.notListeningStatus) _finish();
      },
    );
    _tts.setProgressHandler((_, _, _, _) => _onWord?.call());
    return _ready!;
  }

  void _finish() {
    final f = _onWords;
    _onWords = null;
    _onError = null;
    f?.call(_heard, true);
  }

  void _failed(SpeechRecognitionError e) {
    // No match and a speech timeout are what the recognisers report for silence.
    if (e.errorMsg == 'error_no_match' || e.errorMsg == 'error_speech_timeout') {
      _finish();
      return;
    }
    final f = _onError;
    _onWords = null;
    _onError = null;
    f?.call(e.errorMsg.contains('permission') ? VoiceError.microphone : VoiceError.recognition);
  }

  @override
  Future<void> listen(void Function(String words, bool last) onWords,
      {void Function(double level)? onLevel, void Function(VoiceError error)? onError}) async {
    if (!await canListen()) {
      onError?.call(VoiceError.microphone);
      return;
    }
    await quiet();
    _heard = '';
    _onWords = onWords;
    _onError = onError;
    _onLevel = onLevel;
    await _speech.listen(
      onResult: (SpeechRecognitionResult r) {
        _heard = r.recognizedWords;
        if (r.finalResult) {
          _finish();
        } else {
          _onWords?.call(_heard, false);
        }
      },
      // The level comes in dB, roughly −2 (quiet) to 10 (loud).
      onSoundLevelChange: (db) => _onLevel?.call(((db + 2) / 12).clamp(0.0, 1.0)),
      listenOptions: SpeechListenOptions(
        partialResults: true,
        listenMode: ListenMode.dictation,
        pauseFor: const Duration(seconds: 3),
        listenFor: const Duration(seconds: 60),
      ),
    );
  }

  @override
  Future<void> stopListening() async {
    _onWords = null;
    _onError = null;
    await _speech.stop();
  }

  @override
  Future<void> speak(String text, {void Function()? onWord}) async {
    _onWord = onWord;
    await _tts.awaitSpeakCompletion(true);
    await _tts.speak(text);
    _onWord = null;
  }

  @override
  Future<void> quiet() async {
    _onWord = null;
    await _tts.stop();
  }

  // flutter_tts: 0.5 is the normal pace on Android and iOS.
  @override
  Future<void> setRate(double rate) => _tts.setSpeechRate(0.5 * rate);
}

/// The answer as it should be heard: no Markdown marks, no link targets, no code fences.
String spoken(String text) => text
    .replaceAll(RegExp(r'```[\s\S]*?```'), ' ')
    .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^)]*\)'), (m) => m[1]!)
    .replaceAll(RegExp(r'[*_`#>|]'), '')
    .replaceAll(RegExp(r'^\s*[-•]\s+', multiLine: true), '')
    .replaceAll(RegExp(r'[ \t]+'), ' ')
    .trim();
