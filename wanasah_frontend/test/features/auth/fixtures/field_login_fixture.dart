Map<String, dynamic> fieldLogin({Map<String, dynamic> changes = const {}}) => {
  'token': 'access-token', 'refresh_token': 'refresh-token',
  'principal_id': 101, 'representative_id': 202, 'company_id': 7,
  'company_code': 'WNS-01', 'channel': 'FIELD',
  'principal_type': 'FIELD_REPRESENTATIVE',
  'legacy_driver_id': 303, 'driver_id': 303,
  'driver_name': 'Display only', 'dashboard_access': false,
  ...changes,
};
