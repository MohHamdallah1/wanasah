import '../../../../core/db/local_database.dart';
import '../../../../models/visit_model.dart';

abstract interface class VisitListDataSource {
  Future<List<VisitModel>> readVisits();
}

class LocalVisitListDataSource implements VisitListDataSource {
  LocalVisitListDataSource({LocalDatabase? database})
      : _database = database ?? LocalDatabase.instance;

  final LocalDatabase _database;

  @override
  Future<List<VisitModel>> readVisits() async {
    final rows = await _database.getVisits();
    return rows
        .map((row) => VisitModel.fromJson(Map<String, dynamic>.from(row)))
        .toList();
  }
}
