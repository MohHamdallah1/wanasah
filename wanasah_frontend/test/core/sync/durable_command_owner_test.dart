import 'dart:io';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';
import 'package:wanasah_frontend/core/sync/durable_command.dart';
import 'package:wanasah_frontend/core/sync/durable_command_owner.dart';
import 'package:wanasah_frontend/core/sync/pending_command_store.dart';
import 'package:wanasah_frontend/features/auth/application/stored_auth_identity.dart';
import 'package:wanasah_frontend/features/auth/data/secure_auth_identity_store.dart';
import '../../features/auth/fixtures/field_login_fixture.dart';

class _Database extends Fake implements Database {
  final rows = <Map<String, Object?>>[];
  @override
  Future<int> insert(String table, Map<String, Object?> values, {
    String? nullColumnHack, ConflictAlgorithm? conflictAlgorithm,
  }) async {
    expect(table, 'pending_sync');
    rows.add(Map.of(values));
    return rows.length;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  for (final type in [DurableCommandType.submitSale, DurableCommandType.transferResponse]) {
    test('new $type persists Backend-mapped owner, never principal/profile alias', () async {
      await SecureAuthIdentityStore().persistLogin(StoredAuthIdentity.fromLogin(fieldLogin())!);
      final owner = await SecureAuthIdentityStore().requireCommandOwner('WNS-01');
      final db = _Database();
      final store = PendingCommandStore(databaseProvider: () async => db, tenantProvider: () => 'WNS-01');
      await store.add(type: type, payload: '{"unchanged":"semantic-body"}',
        commandId: 'stable-command', ownerDriverId: owner.driverId);
      expect(db.rows.single['owner_company_code'], 'WNS-01');
      expect(db.rows.single['owner_driver_id'], 303);
      expect(db.rows.single['owner_driver_id'], isNot(101));
      expect(db.rows.single['owner_driver_id'], isNot(202));
      expect(db.rows.single['payload'], '{"unchanged":"semantic-body"}');
      expect(db.rows.single['command_id'], 'stable-command');
    });

    test('$type cannot silently insert a null/invalid owner even if caller forgets plumbing', () async {
      final db = _Database();
      final store = PendingCommandStore(databaseProvider: () async => db, tenantProvider: () => 'WNS-01');
      for (final owner in <int?>[null, 0, -1]) {
        await expectLater(store.add(type: type, payload: '{}', ownerDriverId: owner),
          throwsA(isA<DurableCommandOwnerException>()));
      }
      expect(db.rows, isEmpty);
    });
  }

  test('tenant switch during database acquisition cannot stamp another company onto a command', () async {
    final db = _Database();
    var tenant = 'WNS-01';
    final store = PendingCommandStore(databaseProvider: () async {
      tenant = 'WNS-02';
      return db;
    }, tenantProvider: () => tenant);
    await expectLater(store.add(type: 'submit_sale', payload: '{}', ownerDriverId: 303),
      throwsA(isA<DurableCommandOwnerException>()));
    expect(db.rows, isEmpty);
  });

  test('replay never claims null, foreign or quarantined owner evidence', () {
    final owner = DurableCommandOwner(companyCode: 'WNS-01', driverId: 303);
    for (final row in [
      {'type': 'submit_sale', 'owner_company_code': 'WNS-01', 'owner_driver_id': null},
      {'type': 'transfer_response', 'owner_company_code': 'WNS-01', 'owner_driver_id': 202},
      {'type': 'quarantined_submit_sale', 'state': 'blocked',
        'owner_company_code': 'WNS-02', 'owner_driver_id': 303},
    ]) {
      final before = Map.of(row);
      expect(() => owner.requireRows([row]), throwsA(isA<DurableCommandOwnerException>()));
      expect(row, before);
    }
    owner.requireRows([{'type': 'quarantined_transfer_response', 'state': 'blocked',
      'owner_company_code': 'WNS-01', 'owner_driver_id': 303}]);
  });

  test('runtime staging and replay bind owner before mutation or legacy UUID repair', () {
    final sync = File('lib/repositories/sync_repository.dart').readAsStringSync();
    final visitStart = sync.indexOf('Future<void> saveInvoice(');
    final visitEnd = sync.indexOf('Future<void> _finalizeVisitCommandLocalState(', visitStart);
    final visit = sync.substring(visitStart, visitEnd);
    expect(visit, contains('ownerDriverId: owner.driverId'));
    expect(visit.indexOf('requireCommandOwner'), lessThan(visit.indexOf('stageVisitCommandAtomic(')));
    final transfer = File('lib/features/custody/data/transfer_decision_store.dart').readAsStringSync();
    expect(transfer, contains('ownerDriverId: owner.driverId'));
    expect(transfer.indexOf('owner.requireRows(unresolved)'), lessThan(transfer.indexOf('commandId = _uuid.v4()')));
    final replay = sync.substring(sync.indexOf('Future<int> syncUp()'));
    expect(replay.indexOf('owner.requireRows(pending)'), lessThan(replay.indexOf("payload['request_id'] = _uuid.v4()")));
    expect(replay.indexOf('owner.requireRows(pending)'), lessThan(replay.indexOf('_dispatchPendingRecord(')));
  });

  test('canonical identity and owner code do not read client role/admin flags', () {
    for (final path in [
      'lib/features/auth/application/field_principal_identity.dart',
      'lib/features/auth/application/stored_auth_identity.dart',
      'lib/features/auth/data/secure_auth_identity_store.dart',
      'lib/core/sync/durable_command_owner.dart',
    ]) {
      final source = File(path).readAsStringSync();
      for (final key in ['is_admin', 'is_authorized', 'is_owner', "['role']", "['message']"]) {
        expect(source, isNot(contains(key)), reason: path);
      }
    }
  });
}
