import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../core/problem.dart';
import '../../domain/models.dart';
import '../../widgets/attribute_form.dart';
import '../../widgets/common.dart';
import '../capture/proposal_tile.dart';

/// Editing a record's attributes, respecting what its type actually allows (see AttributeFields). A text
/// field can also be read from a photo: not full nameplate OCR, the same AI reading the registration photo
/// already uses, scoped to the one field asked for and never applied until the person takes it (§23.11).
class AssetEditScreen extends ConsumerStatefulWidget {
  const AssetEditScreen({super.key, required this.uid});

  final String uid;

  @override
  ConsumerState<AssetEditScreen> createState() => _AssetEditScreenState();
}

class _AssetEditScreenState extends ConsumerState<AssetEditScreen> {
  final _form = AttributeFormController();
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _form.dispose();
    super.dispose();
  }

  /// A photo's reading of one field, once the person takes it; null leaves the field as it was.
  Future<String?> _scan(AttributeDef def, AssetDetail a) async {
    final photo = await ref.read(photoSourceProvider).take();
    if (photo == null || !mounted) return null;
    final draft = {
      'uid': a.uid,
      'name': a.name,
      'schema_uid': a.schemaUid,
      'attributes': {for (final e in a.attributes.entries) e.key: e.value},
    };
    try {
      final result = await ref.read(intakeRepositoryProvider).assistAssetPhoto(photo, draft);
      if (!mounted) return null;
      final proposal = result.proposals['attributes.${def.key}'];
      if (proposal == null) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Nothing read for ${def.name} in that photo.')));
        return null;
      }
      // The sheet only reports whether "Use" was pressed; the field is changed afterwards, once the sheet
      // has finished closing — mutating state from inside the sheet's own subtree, in the same tap that pops
      // it, is what a Flutter Navigator assertion exists to catch.
      final taken = await showModalBottomSheet<bool>(
        context: context,
        builder: (sheetContext) => SafeArea(
          child: ProposalTile(proposal, onTake: () => Navigator.of(sheetContext).pop(true)),
        ),
      );
      return taken == true ? proposal.display : null;
    } on Problem catch (p) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('The photo could not be read (${p.message}).')));
      }
      return null;
    }
  }

  Future<void> _save(AssetDetail a, List<AttributeDef> editable) async {
    final problem = _form.validate(editable);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    final attributes = _form.collect(editable, a.attributes);
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(assetRepositoryProvider).save(a, attributes, key: '${a.uid}-${DateTime.now().millisecondsSinceEpoch}');
      refreshAsset(ref, a.uid);
      if (mounted) context.pop();
    } on Problem catch (p) {
      if (p.code == ProblemCode.stale) {
        ref.invalidate(assetDetailProvider(a.uid));
        setState(() => _error = 'Someone changed this record meanwhile. Reopen it and try again.');
      } else {
        setState(() => _error = p.message);
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = ref.watch(assetDetailProvider(widget.uid));
    return Scaffold(
      appBar: AppBar(title: Text('Edit ${detail.value?.name ?? ''}')),
      body: detail.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(assetDetailProvider(widget.uid))),
        data: (a) => Consumer(builder: (context, ref, _) {
          final defsAsync = ref.watch(schemaAttributesProvider(a.schemaUid));
          return defsAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => ProblemView(e, onRetry: () => ref.invalidate(schemaAttributesProvider(a.schemaUid))),
            data: (defs) {
              for (final def in defs) {
                _form.ensure(def, a.attributes);
              }
              final editable = oneVendorField(defs.where((d) => d.editable).toList(), a.attributes, form: true);
              final readOnly = defs.where((d) => !d.editable).toList();
              return ListView(
                key: const Key('asset-edit-list'),
                padding: const EdgeInsets.all(16),
                children: [
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: NoticeBar(icon: Icons.error_outline, text: _error!, severe: true),
                    ),
                  AttributeFields(defs: editable, controller: _form, onScan: (def) => _scan(def, a)),
                  if (readOnly.isNotEmpty) ...[
                    const SectionHeader('Edited on the web'),
                    for (final def in readOnly)
                      ListTile(
                        dense: true,
                        title: Text(def.name),
                        subtitle: Text('${def.type} — this kind of field is edited in the web app, not here'),
                      ),
                  ],
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('asset-edit-save'),
                    onPressed: _saving ? null : () => _save(a, editable),
                    child: _saving
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Save'),
                  ),
                ],
              );
            },
          );
        }),
      ),
    );
  }
}
