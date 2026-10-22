import 'dart:async';

import 'package:flutter/foundation.dart';

import 'voice.dart';

/// Where a hands-free conversation is: waiting, hearing the person, working out the answer, saying it, or stopped
/// by a problem.
enum TurnState { idle, listening, processing, speaking, error }

/// What went wrong, each with its own message and the same remedy: try again.
enum TurnError { network, microphone, recognition, answer }

/// An answer that could not be had: ARGUS unreachable ([TurnError.network]) or refusing ([TurnError.answer]).
class AskFailure implements Exception {
  const AskFailure(this.kind, this.message);
  final TurnError kind;
  final String message;
}

/// What the person can say instead of a question.
enum VoiceCommand { stop, repeat, slower, showSource, yes, no }

/// The command [words] are, if they are one: a short utterance, in Italian or English. "Yes" and "no" count only
/// while details are on offer ([offering]).
VoiceCommand? commandIn(String words, {bool offering = false}) {
  final w = words.toLowerCase().replaceAll(RegExp(r"[^\p{L}\s']", unicode: true), ' ').replaceAll(RegExp(r'\s+'), ' ').trim();
  if (w.isEmpty || w.split(' ').length > 5) return null;
  bool any(List<String> options) => options.contains(w);
  if (any(['stop', 'basta', 'fine', 'ferma', 'fermati', 'esci', 'chiudi', 'stop listening', 'that is all', "that's all"])) {
    return VoiceCommand.stop;
  }
  if (any(['ripeti', 'ripetilo', 'puoi ripetere', 'ripeti per favore', 'repeat', 'repeat that', 'say again', 'say that again', 'come'])) {
    return VoiceCommand.repeat;
  }
  if (any(['più lentamente', 'piu lentamente', 'più piano', 'piu piano', 'lentamente', 'parla più piano', 'slower', 'slow down', 'more slowly', 'speak slower'])) {
    return VoiceCommand.slower;
  }
  if (any(['mostra la fonte', 'mostra le fonti', 'la fonte', 'le fonti', 'fonte', 'fonti', 'show the source', 'show me the source', 'show sources', 'show the sources', 'source', 'sources'])) {
    return VoiceCommand.showSource;
  }
  if (offering) {
    if (any(['sì', 'si', 'sì grazie', 'si grazie', 'dettagli', 'i dettagli', 'vai', 'continua', 'dimmi', 'yes', 'yes please', 'details', 'the details', 'go on', 'sure', 'ok', 'okay'])) {
      return VoiceCommand.yes;
    }
    if (any(['no', 'no grazie', 'basta così', 'basta cosi', 'no thanks', 'no thank you', 'not now'])) return VoiceCommand.no;
  }
  return null;
}

/// Italian or English, from the words: what the spoken prompts are said in.
String languageOf(String text, {String fallback = 'en'}) {
  final words = text.toLowerCase().split(RegExp(r'[^\p{L}]+', unicode: true)).toSet();
  const it = {'il', 'lo', 'la', 'gli', 'le', 'di', 'che', 'è', 'per', 'non', 'una', 'un', 'sono', 'della', 'del', 'con', 'questo', 'quale', 'come'};
  const en = {'the', 'of', 'and', 'is', 'to', 'for', 'not', 'a', 'an', 'are', 'with', 'this', 'which', 'what', 'how'};
  final i = words.intersection(it).length, e = words.intersection(en).length;
  return i == e ? fallback : (i > e ? 'it' : 'en');
}

/// What is said of an answer at first: its opening sentences, up to about [limit] characters; and the rest, kept
/// for "the details" (null when there is nothing more).
({String short, String? rest}) splitForSpeech(String text, {int limit = 260}) {
  final sentences = RegExp(r'[^.!?\n]+[.!?]*', multiLine: true).allMatches(text).map((m) => m[0]!.trim()).where((s) => s.isNotEmpty).toList();
  if (sentences.isEmpty) return (short: text.trim(), rest: null);
  final short = <String>[];
  var length = 0;
  for (final s in sentences) {
    if (short.isNotEmpty && (length + s.length > limit || short.length >= 3)) break;
    short.add(s);
    length += s.length + 1;
  }
  final rest = sentences.skip(short.length).join(' ').trim();
  return (short: short.join(' '), rest: rest.isEmpty ? null : rest);
}

const _phrases = {
  'it': {
    'details': 'Vuoi i dettagli?',
    'source': 'Le fonti sono sullo schermo.',
    'nothing': 'Non ho ancora detto nulla da ripetere.',
  },
  'en': {
    'details': 'Do you want the details?',
    'source': 'The sources are on the screen.',
    'nothing': 'There is nothing to repeat yet.',
  },
};

/// The turns of a hands-free conversation, as an explicit state machine:
///
///     idle ──start──▶ listening ──words──▶ processing ──answer──▶ speaking ──said──▶ listening …
///                        │  ▲                   │                    │
///                silence └──┘ (restarted)     failure            interrupt ──▶ listening
///                        │                      ▼
///                     failure ──────────────▶ error ──retry──▶ listening / processing
///
/// Every asynchronous step carries the turn it belongs to ([_epoch]); a callback of an earlier turn — the
/// recogniser finishing after a stop, an answer arriving after a new conversation, the voice ending after an
/// interruption — finds a newer turn and does nothing. Silence keeps the mode on: listening is restarted, and
/// after [silenceLimit] of nothing it waits, idle, for a tap. "Stop" or the close control ends it.
class VoiceTurns extends ChangeNotifier {
  VoiceTurns({
    required this.voice,
    required this.ask,
    this.onShowSource,
    this.language = 'en',
    this.silenceLimit = const Duration(minutes: 3),
    DateTime Function()? clock,
  }) : _now = clock ?? DateTime.now;

  final Voice voice;

  /// Sends the question; completes with the answer's text, or throws [AskFailure].
  final Future<String> Function(String question) ask;

  /// "Show the source": the screen shows where the last answer comes from.
  final void Function()? onShowSource;
  final Duration silenceLimit;
  final DateTime Function() _now;

  TurnState state = TurnState.idle;
  bool active = false;
  String partial = '';
  double level = 0;
  int words = 0; // spoken words so far in this answer: the waves follow them
  TurnError? error;
  String? errorDetail;
  bool detailsOffered = false;
  bool micOpen = false; // listening is really on (not between two sessions)
  double rate = 1;
  /// What the spoken prompts are said in: 'it' or 'en', from what the person says.
  String language;

  int _epoch = 0;
  String? _lastQuestion;
  String? _lastSpoken;
  String? _rest;
  DateTime? _silentSince;
  int _quickEmpty = 0;
  bool _disposed = false;

  void _set(void Function() change) {
    if (_disposed) return;
    change();
    notifyListeners();
  }

  // ---------------------------------------------------------------- the mode

  /// Hands-free on: listening starts.
  Future<void> start() async {
    _set(() => active = true);
    await _listen();
  }

  /// Hands-free off (the close control, "stop", leaving the screen): nothing more is heard or said.
  Future<void> stop() async {
    _epoch++;
    _set(() {
      active = false;
      state = TurnState.idle;
      partial = '';
      micOpen = false;
      detailsOffered = false;
    });
    await voice.stopListening();
    await voice.quiet();
  }

  /// A new conversation: what was under way belongs to the old one and is dropped.
  Future<void> reset() async {
    _epoch++;
    _lastQuestion = _lastSpoken = _rest = null;
    _set(() {
      detailsOffered = false;
      partial = '';
    });
    await voice.stopListening();
    await voice.quiet();
    if (active) await _listen();
  }

  /// Back to listening from waiting idle (a tap on the orb).
  Future<void> resume() async {
    if (!active) return start();
    if (state == TurnState.idle) await _listen();
  }

  /// Stop the answer being said and listen at once.
  Future<void> interrupt() async {
    if (state != TurnState.speaking) return;
    _epoch++;
    await voice.quiet();
    await _listen();
  }

  /// After a problem: the question again if it was the answer that failed, else listen again.
  Future<void> retry() async {
    if (state != TurnState.error) return;
    final again = (error == TurnError.network || error == TurnError.answer) ? _lastQuestion : null;
    _set(() {
      error = null;
      errorDetail = null;
    });
    if (again != null) {
      await _question(again);
    } else {
      await _listen();
    }
  }

  @override
  void dispose() {
    _epoch++;
    _disposed = true;
    voice.stopListening();
    voice.quiet();
    super.dispose();
  }

  // ---------------------------------------------------------------- listening

  Future<void> _listen() async {
    if (!active || _disposed) return;
    final turn = ++_epoch;
    _set(() {
      state = TurnState.listening;
      partial = '';
      level = 0;
      micOpen = false;
    });
    if (!await voice.canListen()) {
      if (turn == _epoch) _fail(TurnError.microphone);
      return;
    }
    if (turn != _epoch) return;
    final started = _now();
    await voice.listen(
      (heard, last) {
        if (turn != _epoch) return; // a session that was stopped or replaced
        if (!last) {
          _set(() => partial = heard);
          return;
        }
        _set(() {
          partial = heard;
          micOpen = false;
        });
        _heard(heard.trim(), _now().difference(started));
      },
      onLevel: (l) {
        if (turn == _epoch) _set(() => level = l);
      },
      onError: (e) {
        if (turn == _epoch) _fail(e == VoiceError.microphone ? TurnError.microphone : TurnError.recognition);
      },
    );
    if (turn == _epoch && state == TurnState.listening) _set(() => micOpen = true);
  }

  void _heard(String heard, Duration took) {
    if (heard.isEmpty) {
      // Silence: the mode stays on. A recogniser that keeps ending at once is broken, not quiet.
      _quickEmpty = took < const Duration(milliseconds: 400) ? _quickEmpty + 1 : 0;
      if (_quickEmpty >= 5) {
        _quickEmpty = 0;
        _fail(TurnError.recognition);
        return;
      }
      _silentSince ??= _now();
      if (_now().difference(_silentSince!) >= silenceLimit) {
        _silentSince = null;
        _set(() {
          state = TurnState.idle; // waiting for a tap: not listening, and shown so
          detailsOffered = false;
        });
        return;
      }
      _listen();
      return;
    }
    _silentSince = null;
    _quickEmpty = 0;
    language = languageOf(heard, fallback: language);
    switch (commandIn(heard, offering: detailsOffered)) {
      case VoiceCommand.stop:
        stop();
      case VoiceCommand.repeat:
        _say(_lastSpoken ?? _phrase('nothing'));
      case VoiceCommand.slower:
        rate = (rate - 0.2).clamp(0.5, 1.0);
        voice.setRate(rate).then((_) => _say(_lastSpoken ?? _phrase('nothing')));
      case VoiceCommand.showSource:
        onShowSource?.call();
        _say(_phrase('source'), remember: false);
      case VoiceCommand.yes:
        final rest = _rest;
        _rest = null;
        detailsOffered = false;
        _say(rest ?? _phrase('nothing'));
      case VoiceCommand.no:
        _rest = null;
        detailsOffered = false;
        _listen();
      case null:
        _question(heard);
    }
  }

  String _phrase(String key) => _phrases[language]?[key] ?? _phrases['en']![key]!;

  // ---------------------------------------------------------------- answering

  Future<void> _question(String question) async {
    final turn = ++_epoch;
    _lastQuestion = question;
    _set(() {
      state = TurnState.processing;
      detailsOffered = false;
      micOpen = false;
    });
    await voice.stopListening();
    String answer;
    try {
      answer = await ask(question);
    } on AskFailure catch (f) {
      if (turn == _epoch) _fail(f.kind, f.message);
      return;
    }
    if (turn != _epoch || !active) return; // stopped, interrupted or a new conversation meanwhile
    final text = spoken(answer);
    if (text.isEmpty) {
      _fail(TurnError.answer);
      return;
    }
    language = languageOf(text, fallback: language);
    final parts = splitForSpeech(text);
    _rest = parts.rest;
    await _say(parts.rest == null ? parts.short : '${parts.short} ${_phrase('details')}', offer: parts.rest != null);
  }

  /// Say [text], then listen again (unless stopped, interrupted or replaced meanwhile).
  Future<void> _say(String text, {bool offer = false, bool remember = true}) async {
    final turn = ++_epoch;
    if (remember) _lastSpoken = text;
    _set(() {
      state = TurnState.speaking;
      words = 0;
      micOpen = false;
    });
    await voice.speak(text, onWord: () {
      if (turn == _epoch) _set(() => words++);
    });
    if (turn != _epoch || !active) return;
    detailsOffered = offer;
    await _listen();
  }

  void _fail(TurnError kind, [String? detail]) {
    _epoch++;
    voice.stopListening();
    voice.quiet();
    _set(() {
      state = TurnState.error;
      error = kind;
      errorDetail = detail;
      micOpen = false;
    });
  }
}

/// The state, in words: shown under the orb, and what screen readers announce.
String stateLabel(TurnState state, {required String language, bool micOpen = true, bool active = true}) {
  final it = language == 'it';
  return switch (state) {
    TurnState.idle => active ? (it ? 'Pronto quando vuoi — tocca per parlare' : 'Ready when you are — tap to speak') : (it ? 'Pronto quando vuoi' : 'Ready when you are'),
    TurnState.listening => micOpen ? (it ? 'Ti ascolto' : 'Listening') : (it ? 'Riavvio l’ascolto…' : 'Starting to listen…'),
    TurnState.processing => it ? 'Sto cercando e preparo la risposta' : 'Looking it up and preparing the answer',
    TurnState.speaking => it ? 'ARGUS sta rispondendo' : 'ARGUS is answering',
    TurnState.error => it ? 'Si è verificato un problema' : 'Something went wrong',
  };
}

String errorMessage(TurnError error, {required String language, String? detail}) {
  final it = language == 'it';
  final base = switch (error) {
    TurnError.network => it ? 'ARGUS non è raggiungibile: controlla la rete.' : 'ARGUS cannot be reached: check the network.',
    TurnError.microphone => it
        ? 'Il microfono non è disponibile o non è consentito per ARGUS Field.'
        : 'The microphone is not available or not allowed for ARGUS Field.',
    TurnError.recognition => it ? 'Il riconoscimento vocale non ha funzionato.' : 'Speech recognition did not work.',
    TurnError.answer => it ? 'ARGUS non è riuscito a rispondere.' : 'ARGUS could not answer.',
  };
  return detail == null || detail.isEmpty ? base : '$base $detail';
}
