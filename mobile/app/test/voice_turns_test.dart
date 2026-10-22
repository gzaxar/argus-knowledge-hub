import 'dart:async';

import 'package:argus_field/features/ask/voice.dart';
import 'package:argus_field/features/ask/voice_turns.dart';
import 'package:flutter_test/flutter_test.dart';

/// A voice the test speaks for: it says what the person said, when, and when the phone stops talking.
class ScriptedVoice implements Voice {
  bool allowed = true;
  void Function(String, bool)? _words;
  void Function(VoiceError)? _error;
  int listens = 0, stops = 0, quiets = 0;
  final said = <String>[];
  Completer<void>? _speaking;
  double rate = 1;

  @override
  bool get canListenWhileSpeaking => false;

  @override
  Future<bool> canListen() async => allowed;

  @override
  Future<void> listen(void Function(String words, bool last) onWords,
      {void Function(double level)? onLevel, void Function(VoiceError error)? onError}) async {
    listens++;
    _words = onWords;
    _error = onError;
    onLevel?.call(0.5);
  }

  @override
  Future<void> stopListening() async => stops++;

  @override
  Future<void> speak(String text, {void Function()? onWord}) {
    said.add(text);
    onWord?.call();
    _speaking = Completer<void>();
    return _speaking!.future;
  }

  @override
  Future<void> quiet() async {
    quiets++;
    if (_speaking != null && !_speaking!.isCompleted) _speaking!.complete();
  }

  @override
  Future<void> setRate(double r) async => rate = r;

  /// The person said [words] and paused (the recogniser's final result).
  void hear(String words) => _words?.call(words, true);
  void partial(String words) => _words?.call(words, false);
  void fail(VoiceError e) => _error?.call(e);

  /// The phone finished saying what it was saying.
  void doneSpeaking() {
    if (_speaking != null && !_speaking!.isCompleted) _speaking!.complete();
  }

  /// The callbacks of the session before the current one, for late calls.
  void Function(String, bool)? get stale => _words;
}

Future<void> settle() async {
  for (var i = 0; i < 30; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

class World {
  World({this.answer = 'La pompa IP-02 è nella sezione 1.'}) {
    turns = VoiceTurns(voice: voice, ask: _ask, onShowSource: () => sources++, language: 'it', clock: () => now);
  }

  final voice = ScriptedVoice();
  late final VoiceTurns turns;
  DateTime now = DateTime(2026, 10, 22, 10);
  String answer;
  final asked = <String>[];
  Completer<String>? pending;
  AskFailure? failure;
  int sources = 0;

  Future<String> _ask(String q) {
    asked.add(q);
    if (failure != null) {
      final f = failure!;
      failure = null;
      return Future.error(f);
    }
    pending = Completer<String>();
    return pending!.future;
  }

  void tick([Duration d = const Duration(seconds: 3)]) => now = now.add(d);

  /// A whole question: said, answered, and the answer said.
  Future<void> ask(String question) async {
    tick();
    voice.hear(question);
    await settle();
    pending!.complete(answer);
    await settle();
  }
}

void main() {
  group('commands, language and what is said first', () {
    test('commands are short utterances, in Italian or English', () {
      expect(commandIn('Stop'), VoiceCommand.stop);
      expect(commandIn('basta!'), VoiceCommand.stop);
      expect(commandIn('ripeti'), VoiceCommand.repeat);
      expect(commandIn('say that again'), VoiceCommand.repeat);
      expect(commandIn('più lentamente'), VoiceCommand.slower);
      expect(commandIn('Mostra la fonte'), VoiceCommand.showSource);
      expect(commandIn('show me the source'), VoiceCommand.showSource);
      expect(commandIn('sì'), isNull, reason: 'yes only while details are on offer');
      expect(commandIn('sì', offering: true), VoiceCommand.yes);
      expect(commandIn('no grazie', offering: true), VoiceCommand.no);
      expect(commandIn('stop the pump in sector three now please'), isNull, reason: 'a question, not a command');
    });

    test('a long answer is said in short, with the rest kept', () {
      final s = splitForSpeech('Uno. Due. Tre. Quattro è più lunga. Cinque.');
      expect(s.short, 'Uno. Due. Tre.');
      expect(s.rest, 'Quattro è più lunga. Cinque.');
      expect(splitForSpeech('Breve.').rest, isNull);
      expect(languageOf('Dove è la pompa della sezione?'), 'it');
      expect(languageOf('Where is the pump of the section?'), 'en');
    });
  });

  group('turns', () {
    test('listening, the partial words shown, the question sent once the turn ends, the answer said, listening again',
        () async {
      final w = World();
      await w.turns.start();
      expect(w.turns.state, TurnState.listening);
      expect(w.turns.micOpen, isTrue);
      expect(w.turns.level, 0.5);
      w.voice.partial('dove è la');
      expect(w.turns.partial, 'dove è la');
      expect(w.asked, isEmpty, reason: 'a partial transcript is not a question');

      w.tick();
      w.voice.hear('dove è la pompa IP-02');
      await settle();
      expect(w.turns.state, TurnState.processing);
      expect(w.asked, ['dove è la pompa IP-02']);
      w.pending!.complete(w.answer);
      await settle();
      expect(w.turns.state, TurnState.speaking);
      expect(w.voice.said.single, 'La pompa IP-02 è nella sezione 1.');
      expect(w.turns.words, 1);

      w.voice.doneSpeaking();
      await settle();
      expect(w.turns.state, TurnState.listening);
      expect(w.voice.listens, 2);
    });

    test('silence keeps the mode on: listening restarts, and after a long silence it waits for a tap', () async {
      final w = World();
      await w.turns.start();
      w.tick();
      w.voice.hear('');
      await settle();
      expect(w.turns.active, isTrue);
      expect(w.turns.state, TurnState.listening);
      expect(w.voice.listens, 2, reason: 'restarted');
      expect(w.asked, isEmpty);

      w.tick(const Duration(minutes: 4));
      w.voice.hear('');
      await settle();
      expect(w.turns.state, TurnState.idle, reason: 'not listening any more, and shown so');
      expect(w.turns.active, isTrue);
      await w.turns.resume();
      expect(w.turns.state, TurnState.listening);
    });

    test('a recogniser that keeps ending at once is a recognition problem, not silence', () async {
      final w = World();
      await w.turns.start();
      for (var i = 0; i < 5; i++) {
        w.voice.hear('');
        await settle();
      }
      expect(w.turns.state, TurnState.error);
      expect(w.turns.error, TurnError.recognition);
    });

    test('"stop" ends the mode', () async {
      final w = World();
      await w.turns.start();
      w.tick();
      w.voice.hear('basta');
      await settle();
      expect(w.turns.active, isFalse);
      expect(w.turns.state, TurnState.idle);
      expect(w.asked, isEmpty);
    });

    test('"ripeti", "più lentamente" and "mostra la fonte"', () async {
      final w = World();
      await w.turns.start();
      await w.ask('dove è la pompa');
      w.voice.doneSpeaking();
      await settle();

      w.tick();
      w.voice.hear('ripeti');
      await settle();
      expect(w.voice.said.last, 'La pompa IP-02 è nella sezione 1.');
      w.voice.doneSpeaking();
      await settle();

      w.tick();
      w.voice.hear('più lentamente');
      await settle();
      expect(w.voice.rate, closeTo(0.8, 1e-9));
      expect(w.voice.said.last, 'La pompa IP-02 è nella sezione 1.');
      w.voice.doneSpeaking();
      await settle();

      w.tick();
      w.voice.hear('mostra la fonte');
      await settle();
      expect(w.sources, 1);
      expect(w.voice.said.last, 'Le fonti sono sullo schermo.');
      expect(w.asked, hasLength(1), reason: 'commands are not questions');
    });

    test('a long answer offers the details; "sì" says them, "no" listens', () async {
      final w = World(answer: 'La pompa è nella sezione 1. È stata sostituita nel 2024. Il controller è un Agilent. '
          'La corrente nominale è 5 mA. Il manuale è in DOC-12.');
      await w.turns.start();
      await w.ask('parlami della pompa');
      expect(w.voice.said.last, endsWith('Vuoi i dettagli?'));
      expect(w.voice.said.last, isNot(contains('DOC-12')));
      w.voice.doneSpeaking();
      await settle();
      expect(w.turns.detailsOffered, isTrue);

      w.tick();
      w.voice.hear('sì');
      await settle();
      expect(w.voice.said.last, contains('DOC-12'));
      w.voice.doneSpeaking();
      await settle();
      expect(w.turns.detailsOffered, isFalse);
      expect(w.asked, hasLength(1));
    });

    test('an answer is interrupted from the screen; the end of the old answer does not start another turn', () async {
      final w = World();
      await w.turns.start();
      await w.ask('dove è la pompa');
      expect(w.turns.state, TurnState.speaking);
      await w.turns.interrupt();
      await settle();
      expect(w.turns.state, TurnState.listening);
      final listens = w.voice.listens;
      w.voice.doneSpeaking(); // the old speech ends late
      await settle();
      expect(w.voice.listens, listens);
      expect(w.turns.state, TurnState.listening);
    });
  });

  group('late callbacks', () {
    test('an answer that arrives after "stop" is not said', () async {
      final w = World();
      await w.turns.start();
      w.tick();
      w.voice.hear('dove è la pompa');
      await settle();
      await w.turns.stop();
      w.pending!.complete(w.answer);
      await settle();
      expect(w.voice.said, isEmpty);
      expect(w.turns.state, TurnState.idle);
      expect(w.voice.listens, 1, reason: 'the microphone is not restarted');
    });

    test('an answer of the previous conversation is dropped', () async {
      final w = World();
      await w.turns.start();
      w.tick();
      w.voice.hear('dove è la pompa');
      await settle();
      final old = w.pending!;
      await w.turns.reset();
      old.complete(w.answer);
      await settle();
      expect(w.voice.said, isEmpty);
      expect(w.turns.state, TurnState.listening);
    });

    test('the recogniser finishing after the mode was closed starts nothing', () async {
      final w = World();
      await w.turns.start();
      final late = w.voice.stale!;
      await w.turns.stop();
      late('dove è la pompa', true);
      await settle();
      expect(w.asked, isEmpty);
      expect(w.turns.state, TurnState.idle);
    });
  });

  group('problems', () {
    test('no microphone: its own message, and retry listens again', () async {
      final w = World();
      w.voice.allowed = false;
      await w.turns.start();
      expect(w.turns.state, TurnState.error);
      expect(w.turns.error, TurnError.microphone);
      expect(errorMessage(TurnError.microphone, language: 'it'), contains('microfono'));
      w.voice.allowed = true;
      await w.turns.retry();
      expect(w.turns.state, TurnState.listening);
    });

    test('ARGUS unreachable: its own message, and retry asks the same question again', () async {
      final w = World();
      w.failure = const AskFailure(TurnError.network, '');
      await w.turns.start();
      w.tick();
      w.voice.hear('dove è la pompa');
      await settle();
      expect(w.turns.error, TurnError.network);
      expect(errorMessage(TurnError.network, language: 'it'), contains('rete'));
      unawaited(w.turns.retry()); // the question again: its answer is still on its way
      await settle();
      expect(w.asked, ['dove è la pompa', 'dove è la pompa']);
      expect(w.turns.state, TurnState.processing);
    });

    test('the recogniser failing is a recognition problem', () async {
      final w = World();
      await w.turns.start();
      w.voice.fail(VoiceError.recognition);
      expect(w.turns.error, TurnError.recognition);
      expect(errorMessage(TurnError.recognition, language: 'en'), contains('Speech recognition'));
    });
  });
}
