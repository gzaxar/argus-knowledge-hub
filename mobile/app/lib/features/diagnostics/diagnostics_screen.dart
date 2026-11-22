import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app/providers.dart';

/// Who made the app and under what licence, then what support asks for (flutter-app-design §9):
/// versions, environment, device registration and whether the server answers. No token, no
/// personal data beyond the signed-in label.
class DiagnosticsScreen extends ConsumerWidget {
  const DiagnosticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(activeConfigProvider);
    final session = ref.watch(sessionProvider).value;
    final api = ref.watch(apiServiceProvider);
    final meta = ref.watch(serverMetaProvider);
    Widget row(String k, String? v) => ListTile(dense: true, title: Text(k), subtitle: SelectableText(v ?? '—'));
    return Scaffold(
      appBar: AppBar(title: const Text('About and diagnostics')),
      body: ListView(children: [
        row('App', 'ARGUS Field, the field client of the ARGUS Knowledge Hub'),
        row('Author', 'Andrea Michelotti'),
        row('Email', 'andrea.michelotti@infn.it'),
        row('Licence', 'European Union Public Licence v. 1.2 (EUPL-1.2)'),
        ListTile(
          dense: true,
          title: const Text('Privacy policy'),
          subtitle: Text(config.privacyPolicy.toString()),
          trailing: const Icon(Icons.open_in_new),
          onTap: () => launchUrl(config.privacyPolicy, mode: LaunchMode.externalApplication),
        ),
        ListTile(
          dense: true,
          title: const Text('Help'),
          subtitle: const Text('The guide, with a topic on this app'),
          trailing: const Icon(Icons.open_in_new),
          onTap: () => launchUrl(Uri.https(config.privacyPolicy.host, '/help/mobile-app'),
              mode: LaunchMode.externalApplication),
        ),
        ListTile(
          dense: true,
          title: const Text('Licences'),
          subtitle: const Text('This app and the open-source packages it is built with'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => showLicensePage(
            context: context,
            applicationName: 'ARGUS Field',
            applicationVersion: config.appVersion,
            applicationLegalese: 'Andrea Michelotti <andrea.michelotti@infn.it>\n'
                'Licensed under the European Union Public Licence v. 1.2 (EUPL-1.2).',
          ),
        ),
        row('App version', config.appVersion),
        row('Client header', 'flutter/${config.appVersion}/${api.platform}'),
        row('Environment', config.environment),
        row('Server', config.apiBase),
        row('Signed in as', session?.userLabel),
        row('Sign-in method', session?.authType),
        row('Workspace', session?.workspaceName),
        row('Device registration', session?.deviceId),
        meta.when(
          loading: () => const ListTile(dense: true, title: Text('Server API'), subtitle: Text('checking…')),
          error: (e, _) => ListTile(dense: true, title: const Text('Server API'), subtitle: Text('unreachable: $e')),
          data: (m) => row('Server API', [m['current'] ?? m['version'], if (m['supported'] != null) 'supported ${m['supported']}']
              .whereType<Object>()
              .join(' · ')),
        ),
      ]),
    );
  }
}
