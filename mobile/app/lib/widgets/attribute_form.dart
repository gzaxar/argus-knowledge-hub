import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/providers.dart';
import '../domain/models.dart';

/// The values being edited for a record's type-defined attributes, one slot per value: kept by the screen
/// that owns the form (it reads them back on save), shown and changed by [AttributeFields].
class AttributeFormController {
  final Map<String, List<TextEditingController>> text = {};
  final Map<String, List<bool>> flags = {};
  final Map<String, List<String?>> choices = {};

  /// Start editing [def] from the record's stored [attrs]; a field already started keeps what was typed.
  void ensure(AttributeDef def, Map<String, Object?> attrs) {
    if (text.containsKey(def.key) || flags.containsKey(def.key) || choices.containsKey(def.key)) return;
    final raw = attrs[def.key];
    final values = def.multiValue ? (raw is List ? raw : (raw == null ? const [] : [raw])) : [raw];
    if (def.type == 'boolean') {
      flags[def.key] = values.isEmpty ? [false] : values.map((v) => v == true).toList();
    } else if (def.type == 'enumeration' || (def.type == 'reference' && def.referenceSchemaUid != null)) {
      // An enumeration is stored as its option's label, a reference as the target's uid: either way one
      // value per slot, picked rather than typed.
      choices[def.key] = values.isEmpty ? [null] : values.map((v) => v?.toString()).toList();
    } else {
      text[def.key] =
          (values.isEmpty ? [null] : values).map((v) => TextEditingController(text: v?.toString() ?? '')).toList();
    }
  }

  void dispose() {
    for (final list in text.values) {
      for (final c in list) {
        c.dispose();
      }
    }
  }

  static Object? convert(AttributeDef def, String raw) {
    final t = raw.trim();
    if (t.isEmpty) return null;
    return switch (def.type) {
      'integer' => int.tryParse(t),
      'float' => double.tryParse(t),
      _ => t,
    };
  }

  static String? validateValue(AttributeDef def, String raw) {
    final t = raw.trim();
    if (t.isEmpty) return null; // required/min-cardinality is checked across all values, not per field
    if ((def.type == 'integer' && int.tryParse(t) == null) || (def.type == 'float' && double.tryParse(t) == null)) {
      return 'Not a number';
    }
    if (def.regex != null && def.regex!.isNotEmpty && !RegExp(def.regex!).hasMatch(t)) {
      return "Doesn't match the required pattern";
    }
    if ((def.type == 'date' || def.type == 'datetime') && DateTime.tryParse(t) == null) {
      return 'Not a date (YYYY-MM-DD)';
    }
    return null;
  }

  /// The first problem with what is entered for [defs] (required, cardinality, number, pattern, date), or null.
  String? validate(Iterable<AttributeDef> defs) {
    String? problem;
    for (final def in defs) {
      final count = flags[def.key] != null
          ? flags[def.key]!.length
          : choices[def.key] != null
              ? choices[def.key]!.where((v) => v != null).length
              : (text[def.key] ?? const []).where((c) => c.text.trim().isNotEmpty).length;
      if (def.required && count == 0) problem ??= '${def.name} is required.';
      if (def.minCardinality != null && count < def.minCardinality!) {
        problem ??= '${def.name} needs at least ${def.minCardinality}.';
      }
      if (def.maxCardinality != null && count > def.maxCardinality!) {
        problem ??= '${def.name} allows at most ${def.maxCardinality}.';
      }
      for (final c in text[def.key] ?? const <TextEditingController>[]) {
        final e = validateValue(def, c.text);
        if (e != null) problem ??= '${def.name}: $e';
      }
    }
    return problem;
  }

  /// [base] with the values of [defs] as entered — the other stored attributes travel unchanged.
  Map<String, Object?> collect(Iterable<AttributeDef> defs, Map<String, Object?> base) {
    final out = <String, Object?>{...base};
    for (final def in defs) {
      if (flags[def.key] != null) {
        final values = flags[def.key]!;
        out[def.key] = def.multiValue ? values : values.first;
      } else if (choices[def.key] != null) {
        final values = choices[def.key]!.whereType<String>().toList();
        out[def.key] = def.multiValue ? values : (values.isEmpty ? null : values.first);
      } else {
        final values = (text[def.key] ?? const []).map((c) => convert(def, c.text)).whereType<Object>().toList();
        out[def.key] = def.multiValue ? values : (values.isEmpty ? null : values.first);
      }
    }
    return out;
  }
}

/// The inputs for a record's editable attributes, each by what its type allows: a date picks from a
/// calendar, a yes/no is a switch, an enumeration is its own options, a reference a search among records of
/// its target type — never a bare text box for everything (flutter-app-design §5.4, mirrored from the web
/// form's AttributeInput.tsx). [onScan], when given, offers to read a text field from a photo; it returns
/// the value to put in the field, or null to leave it.
class AttributeFields extends ConsumerStatefulWidget {
  const AttributeFields({super.key, required this.defs, required this.controller, this.onScan});

  final List<AttributeDef> defs;
  final AttributeFormController controller;
  final Future<String?> Function(AttributeDef def)? onScan;

  @override
  ConsumerState<AttributeFields> createState() => _AttributeFieldsState();
}

class _AttributeFieldsState extends ConsumerState<AttributeFields> {
  String? _scanning;

  AttributeFormController get _c => widget.controller;

  Future<void> _pickDate(AttributeDef def, TextEditingController c) async {
    final initial = DateTime.tryParse(c.text) ?? DateTime.now();
    final date =
        await showDatePicker(context: context, initialDate: initial, firstDate: DateTime(1990), lastDate: DateTime(2100));
    if (date == null) return;
    setState(() => c.text = def.type == 'datetime' ? date.toIso8601String() : date.toIso8601String().substring(0, 10));
  }

  Future<void> _scan(AttributeDef def, TextEditingController c) async {
    setState(() => _scanning = def.key);
    try {
      final value = await widget.onScan!(def);
      if (value != null && mounted) setState(() => c.text = value);
    } finally {
      if (mounted) setState(() => _scanning = null);
    }
  }

  @override
  Widget build(BuildContext context) =>
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [for (final def in widget.defs) _field(def)]);

  Widget _field(AttributeDef def) {
    final label = def.name + (def.required ? ' *' : '');
    switch (def.type) {
      case 'boolean':
        final values = _c.flags[def.key]!;
        return SwitchListTile(
          key: Key('attr-${def.key}'),
          title: Text(label),
          value: values.first,
          onChanged: (v) => setState(() => values[0] = v),
        );
      case 'enumeration':
        final values = _c.choices[def.key]!;
        // An answer naming its option by id is the same answer: shown (and kept) as the option's value.
        final current = def.choiceValue(values.first) ?? values.first;
        // The option's label is what is stored and what the web form writes, not its id — the two commonly
        // differ ("in_service" / "In service"). Deduplicated by label, and the record's current value kept as
        // an extra item when it names no listed option: a dropdown must offer exactly one item equal to its
        // value or Flutter refuses to render it at all.
        final labels = <String>{};
        final options = <DropdownMenuItem<String>>[];
        for (final o in def.options) {
          if (labels.add(o.value)) options.add(DropdownMenuItem(value: o.value, child: Text(o.value)));
        }
        if (current != null && labels.add(current)) {
          options.add(DropdownMenuItem(value: current, child: Text('$current (not in the current list)')));
        }
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: DropdownButtonFormField<String>(
            key: Key('attr-${def.key}'),
            initialValue: current,
            decoration: InputDecoration(labelText: label),
            items: [const DropdownMenuItem(value: null, child: Text('—')), ...options],
            onChanged: (v) => setState(() => values[0] = v),
          ),
        );
      case 'reference':
        if (def.referenceSchemaUid == null) return _plainTextField(def, label);
        return _referencePicker(def, label);
      default:
        return _plainTextField(def, label);
    }
  }

  /// The candidates of the reference's target type (and its descendants, when includeChildren) to pick
  /// among, instead of a free-text uid the person could never type correctly — the web's ReferenceInput.
  Widget _referencePicker(AttributeDef def, String label) {
    final values = _c.choices[def.key]!;
    final candidatesAsync = ref.watch(referenceCandidatesProvider((def.referenceSchemaUid!, def.includeChildren)));
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final (i, uid) in values.indexed)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
              Expanded(
                child: candidatesAsync.when(
                  loading: () =>
                      const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: LinearProgressIndicator()),
                  error: (e, _) => Text('Could not load choices: $e'),
                  data: (candidates) => ReferenceField(
                    key: Key('attr-${def.key}-$i'),
                    label: i == 0 ? label : null,
                    candidates: candidates,
                    value: uid,
                    onChanged: (v) => setState(() => values[i] = v),
                  ),
                ),
              ),
              if (def.multiValue)
                IconButton(
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed:
                      values.length <= (def.minCardinality ?? 0) ? null : () => setState(() => values.removeAt(i)),
                ),
            ]),
          ),
        if (def.multiValue && (def.maxCardinality == null || values.length < def.maxCardinality!))
          TextButton.icon(
            onPressed: () => setState(() => values.add(null)),
            icon: const Icon(Icons.add),
            label: Text('Add ${def.name.toLowerCase()}'),
          ),
      ]),
    );
  }

  Widget _plainTextField(AttributeDef def, String label) {
    final controllers = _c.text[def.key]!;
    final isDate = def.type == 'date' || def.type == 'datetime';
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final (i, c) in controllers.indexed)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: TextField(
                  key: Key('attr-${def.key}-$i'),
                  controller: c,
                  maxLines: def.type == 'text' ? 4 : 1,
                  keyboardType:
                      def.type == 'integer' || def.type == 'float' ? TextInputType.number : TextInputType.text,
                  readOnly: isDate,
                  onTap: isDate ? () => _pickDate(def, c) : null,
                  decoration: InputDecoration(
                    labelText: i == 0 ? label : null,
                    hintText: isDate ? 'Tap to choose' : null,
                    helperText: i == 0 ? def.description : null,
                  ),
                ),
              ),
              if (widget.onScan != null && (def.type == 'string' || def.type == 'text'))
                IconButton(
                  key: Key('attr-${def.key}-$i-scan'),
                  tooltip: 'Read from a photo',
                  // Not an animated spinner: the read is a single quick request, and a widget that animates
                  // forever never lets a test (or, just as real, a slow device) settle on it.
                  icon: Icon(_scanning == def.key ? Icons.hourglass_top : Icons.document_scanner_outlined),
                  onPressed: _scanning != null ? null : () => _scan(def, c),
                ),
              if (def.multiValue)
                IconButton(
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: controllers.length <= (def.minCardinality ?? 0)
                      ? null
                      : () => setState(() => controllers.removeAt(i).dispose()),
                ),
            ]),
          ),
        if (def.multiValue && (def.maxCardinality == null || controllers.length < def.maxCardinality!))
          TextButton.icon(
            onPressed: () => setState(() => controllers.add(TextEditingController())),
            icon: const Icon(Icons.add),
            label: Text('Add ${def.name.toLowerCase()}'),
          ),
      ]),
    );
  }
}

/// A search-as-you-type picker among a reference attribute's candidate records — the web form's AssetPicker
/// (name/key search, pick-only: no way to commit a value that isn't one of the candidates). Focusing it clears
/// the query so every candidate shows at once, as AssetPicker's onFocus does.
class ReferenceField extends StatefulWidget {
  const ReferenceField({super.key, required this.candidates, required this.value, required this.onChanged, this.label});

  final List<RecordBrief> candidates;
  final String? value;
  final ValueChanged<String?> onChanged;
  final String? label;

  @override
  State<ReferenceField> createState() => _ReferenceFieldState();
}

class _ReferenceFieldState extends State<ReferenceField> {
  late final TextEditingController _controller;
  late final FocusNode _focusNode;

  String _displayFor(String? value) {
    for (final c in widget.candidates) {
      if (c.uid == value) return c.label;
    }
    return value ?? '';
  }

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: _displayFor(widget.value));
    _focusNode = FocusNode()..addListener(_onFocusChange);
  }

  void _onFocusChange() {
    if (_focusNode.hasFocus) {
      _controller.clear();
    } else if (_controller.text.isEmpty) {
      _controller.text = _displayFor(widget.value); // nothing picked while open: restore it
    }
  }

  @override
  void didUpdateWidget(covariant ReferenceField old) {
    super.didUpdateWidget(old);
    if (widget.value != old.value && !_focusNode.hasFocus) _controller.text = _displayFor(widget.value);
  }

  @override
  void dispose() {
    _focusNode.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RawAutocomplete<RecordBrief>(
      textEditingController: _controller,
      focusNode: _focusNode,
      displayStringForOption: (o) => o.label,
      optionsBuilder: (v) {
        final q = v.text.trim().toLowerCase();
        final matches = q.isEmpty
            ? widget.candidates
            : widget.candidates
                .where((c) => (c.name ?? '').toLowerCase().contains(q) || (c.key ?? '').toLowerCase().contains(q));
        return matches.take(30);
      },
      onSelected: (o) {
        widget.onChanged(o.uid);
        _focusNode.unfocus();
      },
      fieldViewBuilder: (context, controller, focusNode, onFieldSubmitted) => TextField(
        controller: controller,
        focusNode: focusNode,
        decoration: InputDecoration(
          labelText: widget.label,
          hintText: 'Search ${widget.candidates.isEmpty ? '' : widget.candidates.first.type ?? ''}…',
          suffixIcon: widget.value == null
              ? null
              : IconButton(
                  icon: const Icon(Icons.clear),
                  onPressed: () {
                    controller.clear();
                    widget.onChanged(null);
                  },
                ),
        ),
      ),
      optionsViewBuilder: (context, onSelected, options) => Align(
        alignment: Alignment.topLeft,
        child: Material(
          elevation: 4,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 240),
            child: ListView(
              padding: EdgeInsets.zero,
              shrinkWrap: true,
              children: [for (final o in options) ListTile(dense: true, title: Text(o.label), onTap: () => onSelected(o))],
            ),
          ),
        ),
      ),
    );
  }
}
