import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as path;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:sqflite/sqflite.dart' as sqflite;
import 'package:wanasah_frontend/core/db/local_database.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_transfer.dart';
import 'package:wanasah_frontend/features/custody/data/pending_transfer_source.dart';
import 'package:wanasah_frontend/features/custody/presentation/pending_transfer_quantity_formatter.dart';
import 'canonical_transfer_fixture.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory directory;
  final local = LocalDatabase.instance;
  setUpAll(() {
    sqfliteFfiInit();
    sqflite.databaseFactory = databaseFactoryFfi;
  });
  setUp(() async {
    directory = await Directory.systemTemp.createTemp('wanasah-custody-uom-');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('plugins.flutter.io/path_provider'),
          (_) async => directory.path,
        );
    await local.setTenant('CUSTODY_TEST');
  });
  tearDown(() async {
    await local.resetTenant();
  }); // Preserve test files; never delete data.
  const fields = [
    'quantity_contract',
    'signed_base_quantity',
    'base_uom_id',
    'base_uom_code',
    'base_uom_name',
    'quantity_scale',
    'quantity_step',
    'display_uom_name',
    'display_factor_to_base',
  ];
  test(
    'fresh v11 has canonical columns and survives refresh/restart/offline fallback',
    () async {
      final db = await local.database;
      expect(await db.getVersion(), 11);
      final columns = await db.rawQuery(
        'PRAGMA table_info(incoming_transfers)',
      );
      expect(columns.map((row) => row['name']), containsAll(fields));
      final raw = canonicalTransfer(quantity: '25');
      await local.refreshSessionData([], [], [raw]);
      final rows = await local.getIncomingTransfers();
      for (final field in fields) {
        expect(rows.single[field], raw[field]);
      }
      final online = PendingTransferItem.fromServerJson(raw);
      await local.resetTenant();
      await local.setTenant('CUSTODY_TEST');
      final source = PendingTransferSource(
        remoteFetch: () async {
          throw DioException(
            requestOptions: RequestOptions(path: '/driver/transfers/pending'),
            type: DioExceptionType.connectionError,
          );
        },
        localFetch: local.getIncomingTransfers,
      );
      final cached = (await source.load())!;
      expect(cached.fromLocalCache, isTrue);
      expect(
        formatPendingTransferQuantity(cached.items.single, locale: 'en'),
        formatPendingTransferQuantity(online, locale: 'en'),
      );
      expect(
        formatPendingTransferQuantity(cached.items.single, locale: 'en'),
        '3 باكيت + 1 حبة',
      );
      await expectLater(
        local.refreshSessionData([], [], [
          canonicalTransfer()..remove('quantity_step'),
        ]),
        throwsFormatException,
      );
      expect(
        (await local.getIncomingTransfers()).single['signed_base_quantity'],
        '25',
      );
    },
  );
  test(
    'v10 upgrade is additive and preserves legacy rows and other pending evidence',
    () async {
      final old = await databaseFactoryFfi.openDatabase(
        path.join(directory.path, 'wanasah_local_CUSTODY_TEST.db'),
        options: OpenDatabaseOptions(
          version: 10,
          onCreate: (db, _) async {
            await db.execute(
              'CREATE TABLE incoming_transfers (id INTEGER PRIMARY KEY, transfer_id INTEGER, product_variant_id INTEGER, product_name TEXT, delta_cartons INTEGER, delta_packs INTEGER, status TEXT, created_at TEXT, batch_id TEXT)',
            );
            await db.execute(
              'CREATE TABLE pending_sync (id INTEGER PRIMARY KEY, type TEXT, payload TEXT)',
            );
            await db.insert('incoming_transfers', {
              'id': 1,
              'transfer_id': 7,
              'product_name': 'قديم',
              'delta_cartons': 2,
              'delta_packs': 3,
            });
            await db.insert('pending_sync', {
              'id': 1,
              'type': 'unrelated',
              'payload': 'keep exact',
            });
          },
        ),
      );
      await old.close();
      final upgraded = await local.database;
      expect(await upgraded.getVersion(), 11);
      final rows = await local.getIncomingTransfers();
      expect(rows.single['transfer_id'], 7);
      expect(rows.single['quantity_contract'], isNull);
      expect(
        formatPendingTransferQuantity(
          PendingTransferItem.fromLocalRow(rows.single),
          locale: 'en',
        ),
        '2 cartons, 3 pieces',
      );
      expect(
        (await upgraded.query('pending_sync')).single['payload'],
        'keep exact',
      );
      expect(
        (await upgraded.rawQuery(
          'PRAGMA table_info(incoming_transfers)',
        )).map((row) => row['name']),
        containsAll(fields),
      );
    },
  );
}
