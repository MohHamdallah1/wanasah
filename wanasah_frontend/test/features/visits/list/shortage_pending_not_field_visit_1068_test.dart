import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_reader.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_read_model.dart';
import 'package:wanasah_frontend/features/visits/list/data/visit_list_data_source.dart';
import 'package:wanasah_frontend/models/visit_model.dart';

class _SignedVisitRows implements VisitListDataSource {
  _SignedVisitRows(this.rows);
  final List<VisitModel> rows;
  @override
  Future<List<VisitModel>> readVisits() async => List<VisitModel>.of(rows);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Phase B pending replenishment is NOT a FIELD visit or emergency task', () async {
    // A shortage command receipt creates demand evidence only. FIELD's
    // existing consumer receives /driver/visits and local Visit rows; it never
    // consumes Dashboard shortage POST replies or reads a demand table.
    final normal = VisitModel.fromJson(<String, dynamic>{
      'id': 11, 'shop_id': 7, 'shop_name': 'Grocer',
      'status': 'Pending', 'is_emergency': false, 'sequence': 1,
    });
    final actual = await VisitListReader(
      dataSource: _SignedVisitRows(<VisitModel>[normal]),
    ).read();
    expect(actual.orderedRows.map((row) => row.id), <int>[11]);
    expect(actual.emergencyCount, 0);
    expect(actual.rowsFor(VisitRouteKind.emergency), isEmpty);

    // Versioned PENDING_REPLENISHMENT receipt is not an executable Visit
    // payload; it must not acquire a Visit identity by matching shop/SKU.
    expect(
      () => VisitModel.fromJson(<String, dynamic>{
        'request_id': '4ddc9822-7efb-4fc7-8721-ce6cda7ad57c',
        'demand_id': 900, 'shop_id': 7, 'product_id': 40,
        'requested_base': 10, 'fulfilled_base': 0,
        'outstanding_base': 10, 'status': 'PENDING_REPLENISHMENT',
      }),
      throwsFormatException,
    );
  });

  test('Only an actual FIELD visit with explicit backend emergency flag is urgent', () async {
    final ordinary = VisitModel.fromJson(<String, dynamic>{
      'visit_id': 21, 'shop_id': 7, 'status': 'Pending',
      'is_emergency': false, 'sequence': 2,
    });
    final authorizedUrgent = VisitModel.fromJson(<String, dynamic>{
      'visit_id': 22, 'shop_id': 7, 'status': 'Pending',
      'is_emergency': true, 'sequence': 3,
    });
    final result = await VisitListReader(
      dataSource: _SignedVisitRows(<VisitModel>[authorizedUrgent, ordinary]),
    ).read();
    expect(result.rowsFor(VisitRouteKind.normal).map((x) => x.id), <int>[21]);
    expect(result.rowsFor(VisitRouteKind.emergency).map((x) => x.id), <int>[22]);
    expect(result.emergencyCount, 1);
  });
}
