-- 同车合算：一辆车装载多个供货批，按各批到货吨位折算配重后合并诊断。
CREATE TABLE IF NOT EXISTS vehicles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    note text,
    created_by bigint NOT NULL REFERENCES accounts(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vehicle_lots (
    vehicle_id bigint NOT NULL REFERENCES vehicles(id),
    lot_id bigint NOT NULL REFERENCES lots(id),
    PRIMARY KEY (vehicle_id, lot_id)
);
-- 一个供货批在同一时刻只能挂在一辆车上，避免同一批被两套配重重复合算。
CREATE UNIQUE INDEX IF NOT EXISTS vehicle_lots_lot_unique ON vehicle_lots(lot_id);

-- 同车复磅留痕：每次改吨位都追加一行，验收单按当时的配重快照冻结。
CREATE TABLE IF NOT EXISTS lot_weighings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id bigint NOT NULL REFERENCES lots(id),
    shipment_kg integer NOT NULL CHECK (shipment_kg > 0),
    reason text NOT NULL,
    weighed_by bigint NOT NULL REFERENCES accounts(id),
    weighed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lot_weighings_by_lot ON lot_weighings(lot_id, id);

-- 验收版本扩展：整车诊断挂 vehicle_id，单批诊断继续挂 lot_id，二者互斥。
ALTER TABLE inspections ADD COLUMN IF NOT EXISTS vehicle_id bigint REFERENCES vehicles(id);
ALTER TABLE inspections ADD COLUMN IF NOT EXISTS idempotency_key uuid;
ALTER TABLE inspections ADD COLUMN IF NOT EXISTS provisional boolean NOT NULL DEFAULT false;
ALTER TABLE inspections ALTER COLUMN lot_id DROP NOT NULL;
ALTER TABLE inspections DROP CONSTRAINT IF EXISTS inspections_scope_check;
ALTER TABLE inspections ADD CONSTRAINT inspections_scope_check CHECK (
    (lot_id IS NOT NULL AND vehicle_id IS NULL) OR
    (lot_id IS NULL AND vehicle_id IS NOT NULL)
);
ALTER TABLE inspections DROP CONSTRAINT IF EXISTS inspections_lot_id_version_key;
CREATE UNIQUE INDEX IF NOT EXISTS inspections_lot_version_unique
    ON inspections(lot_id, version) WHERE lot_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS inspections_vehicle_version_unique
    ON inspections(vehicle_id, version) WHERE vehicle_id IS NOT NULL;
-- 原单重试：同一幂等键只允许一张验收单，重试直接取回原单而不是新建。
CREATE UNIQUE INDEX IF NOT EXISTS inspections_idempotency_unique
    ON inspections(idempotency_key) WHERE idempotency_key IS NOT NULL;

ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS vehicle_id bigint REFERENCES vehicles(id);
-- 车辆级事件（建档、整车合算、整车发布）不挂具体批号。
ALTER TABLE audit_events ALTER COLUMN lot_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS audit_by_vehicle ON audit_events(vehicle_id, id DESC) WHERE vehicle_id IS NOT NULL;
