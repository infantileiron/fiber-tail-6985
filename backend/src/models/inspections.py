from fastapi import HTTPException

RUN_DETAILS = """
    SELECT i.*,
           l.code AS lot_code, l.supplier, l.material,
           v.code AS vehicle_code,
           requester.display_name AS requester, d.outcome, d.rationale, d.published_at,
           reviewer.display_name AS reviewer
    FROM inspections i
    LEFT JOIN lots l ON l.id = i.lot_id
    LEFT JOIN vehicles v ON v.id = i.vehicle_id
    JOIN accounts requester ON requester.id = i.requested_by
    LEFT JOIN decisions d ON d.inspection_id = i.id
    LEFT JOIN accounts reviewer ON reviewer.id = d.reviewer_id
"""


def get_inspection(db, run_id, published_only=False):
    query = RUN_DETAILS + " WHERE i.id = %s"
    if published_only:
        query += " AND d.inspection_id IS NOT NULL"
    row = db.execute(query, (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到可查看的验收单")
    return row


def list_inspections(db, *, lot_id=None, vehicle_id=None, published_only=False):
    if lot_id is None and vehicle_id is None:
        raise ValueError("list_inspections 需要指定批号或车辆")
    scope_column = "lot_id" if lot_id is not None else "vehicle_id"
    scope_value = lot_id if lot_id is not None else vehicle_id
    return db.execute(f"""
        SELECT i.id, i.version, i.status, i.parameters, i.requested_at, i.completed_at,
               i.provisional, i.result->>'recommendation' AS recommendation,
               d.outcome, d.published_at
        FROM inspections i LEFT JOIN decisions d ON d.inspection_id = i.id
        WHERE i.{scope_column} = %s AND (NOT %s OR d.inspection_id IS NOT NULL)
        ORDER BY i.version DESC
    """, (scope_value, published_only)).fetchall()
