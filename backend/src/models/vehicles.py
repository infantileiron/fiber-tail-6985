from fastapi import HTTPException


def get_vehicle(db, vehicle_id, lock=False):
    query = "SELECT * FROM vehicles WHERE id = %s"
    if lock:
        query += " FOR UPDATE"
    vehicle = db.execute(query, (vehicle_id,)).fetchone()
    if vehicle is None:
        raise HTTPException(404, "找不到这辆车的合算单")
    return vehicle


def list_vehicles(db):
    return db.execute("""
        SELECT v.*, m.member_count, m.total_shipment_kg, m.sample_lots, m.ready_lots,
               d.outcome, d.published_version
        FROM vehicles v
        CROSS JOIN LATERAL (
            SELECT count(*) AS member_count,
                   COALESCE(sum(l.shipment_kg), 0) AS total_shipment_kg,
                   count(s.lot_id) AS sample_lots,
                   count(*) FILTER (WHERE s.sample_count >= %(min)s) AS ready_lots
            FROM vehicle_lots vl
            JOIN lots l ON l.id = vl.lot_id
            LEFT JOIN (SELECT lot_id, count(*) AS sample_count FROM samples GROUP BY lot_id) s
                   ON s.lot_id = vl.lot_id
            WHERE vl.vehicle_id = v.id
        ) m
        LEFT JOIN LATERAL (
            SELECT d.outcome, i.version AS published_version FROM inspections i
            JOIN decisions d ON d.inspection_id = i.id WHERE i.vehicle_id = v.id
            ORDER BY i.version DESC LIMIT 1
        ) d ON true
        ORDER BY v.id DESC
    """, {"min": 3}).fetchall()


def vehicle_lots(db, vehicle_id):
    return db.execute("""
        SELECT l.*, count(s.id) AS sample_count,
               COALESCE(sum(s.dry_g), 0) AS total_dry_g
        FROM vehicle_lots vl
        JOIN lots l ON l.id = vl.lot_id
        LEFT JOIN samples s ON s.lot_id = l.id
        WHERE vl.vehicle_id = %s
        GROUP BY l.id
        ORDER BY l.code
    """, (vehicle_id,)).fetchall()


def add_weighing(db, lot, reason, actor):
    db.execute("""
        INSERT INTO lot_weighings (lot_id, shipment_kg, reason, weighed_by)
        VALUES (%s, %s, %s, %s)
    """, (lot["id"], lot["shipment_kg"], reason, actor))


def weighing_history(db, lot_id):
    return db.execute("""
        SELECT w.shipment_kg, w.reason, w.weighed_at, a.display_name AS weigher
        FROM lot_weighings w JOIN accounts a ON a.id = w.weighed_by
        WHERE w.lot_id = %s ORDER BY w.id
    """, (lot_id,)).fetchall()
