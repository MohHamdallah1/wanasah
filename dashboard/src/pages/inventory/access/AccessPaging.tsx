import type { InventoryAccessCopy } from './copy';

interface AccessPagingProps {
  copy: InventoryAccessCopy;
  next: number | null | undefined;
  current: number;
  busy: boolean;
  onChange: (value: number) => void;
}

export function AccessPaging({ copy, next, current, busy, onChange }: AccessPagingProps) {
  return (
    <span className="inventory-inline-paging">
      <button type="button" disabled={!current || busy} onClick={() => onChange(0)}>
        {copy.first}
      </button>
      <button type="button" disabled={!next || busy} onClick={() => next && onChange(next)}>
        {copy.next}
      </button>
    </span>
  );
}
