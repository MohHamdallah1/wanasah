export interface InventoryAccessCopy {
  rolesEyebrow: string;
  newRole: string;
  editRole: string;
  selectedPermissions: (count: number) => string;
  roleName: string;
  roleNamePlaceholder: string;
  companyOnly: string;
  guidance: string;
  saveRole: string;
  resetRole: string;
  systemRole: string;
  assignmentEyebrow: string;
  grantUser: string;
  user: string;
  chooseUser: string;
  companyOwner: string;
  inactive: string;
  locationScope: string;
  companyScope: string;
  scope: string;
  role: string;
  chooseRole: string;
  warehouseOrVehicle: string;
  chooseLocation: string;
  warehouse: string;
  vehicle: string;
  addGrant: string;
  chooseUserToView: string;
  noGrants: string;
  wholeCompany: string;
  revoke: string;
  first: string;
  next: string;
  confirmRevokeTitle: string;
  confirmRevokeBody: string;
  cancel: string;
  confirmRevoke: string;
}

const ar: InventoryAccessCopy = {
  rolesEyebrow: 'بناء الأدوار',
  newRole: 'دور جديد',
  editRole: 'تعديل دور',
  selectedPermissions: count => `${count} صلاحية محددة`,
  roleName: 'اسم الدور',
  roleNamePlaceholder: 'مثال: مسؤول الاستلام',
  companyOnly: 'على مستوى الشركة فقط',
  guidance: 'امنح أقل نطاق مطلوب للعمل. منح الموقع يبقى محصورًا بالمستودع أو السيارة المحددة، ولا يمنح صلاحيات الشركة تلقائيًا.',
  saveRole: 'حفظ الدور',
  resetRole: 'دور جديد',
  systemRole: 'نظامي',
  assignmentEyebrow: 'الإسناد',
  grantUser: 'منح المستخدم',
  user: 'المستخدم',
  chooseUser: 'اختر المستخدم',
  companyOwner: 'مالك الشركة',
  inactive: 'غير فعال',
  locationScope: 'نطاق موقع',
  companyScope: 'نطاق شركة',
  scope: 'نطاق المنح',
  role: 'الدور',
  chooseRole: 'اختر الدور',
  warehouseOrVehicle: 'المستودع أو السيارة',
  chooseLocation: 'اختر المستودع أو السيارة',
  warehouse: 'مستودع',
  vehicle: 'سيارة',
  addGrant: 'إضافة المنح',
  chooseUserToView: 'اختر مستخدمًا لعرض المنح الحالية.',
  noGrants: 'لا توجد منح ضمن هذا النطاق.',
  wholeCompany: 'الشركة كاملة',
  revoke: 'سحب المنح',
  first: 'البداية',
  next: 'التالي',
  confirmRevokeTitle: 'تأكيد سحب المنح',
  confirmRevokeBody: 'سيتم سحب هذه المنحة فورًا، وستنعكس الصلاحيات الحالية في الطلبات التالية.',
  cancel: 'إلغاء',
  confirmRevoke: 'سحب المنح',
};

const en: InventoryAccessCopy = {
  rolesEyebrow: 'Role design',
  newRole: 'New role',
  editRole: 'Edit role',
  selectedPermissions: count => `${count} permissions selected`,
  roleName: 'Role name',
  roleNamePlaceholder: 'Example: Receiving operator',
  companyOnly: 'Company scope only',
  guidance: 'Grant only the minimum scope required. A location grant stays limited to the selected warehouse or vehicle and never grants company capabilities automatically.',
  saveRole: 'Save role',
  resetRole: 'New role',
  systemRole: 'System',
  assignmentEyebrow: 'Assignment',
  grantUser: 'Grant user access',
  user: 'User',
  chooseUser: 'Choose user',
  companyOwner: 'Company Owner',
  inactive: 'Inactive',
  locationScope: 'Location scope',
  companyScope: 'Company scope',
  scope: 'Grant scope',
  role: 'Role',
  chooseRole: 'Choose role',
  warehouseOrVehicle: 'Warehouse or vehicle',
  chooseLocation: 'Choose warehouse or vehicle',
  warehouse: 'Warehouse',
  vehicle: 'Vehicle',
  addGrant: 'Add grant',
  chooseUserToView: 'Choose a user to view current grants.',
  noGrants: 'No grants exist in this scope.',
  wholeCompany: 'Whole company',
  revoke: 'Revoke grant',
  first: 'First',
  next: 'Next',
  confirmRevokeTitle: 'Confirm grant revocation',
  confirmRevokeBody: 'This grant will be revoked immediately and current authority will apply to following requests.',
  cancel: 'Cancel',
  confirmRevoke: 'Revoke grant',
};

export const inventoryAccessCopy = (language: string): InventoryAccessCopy =>
  language.startsWith('ar') ? ar : en;
