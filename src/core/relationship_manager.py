"""
relationship_manager.py — CLI untuk manage organizations & relationships.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db import (
    get_conn, init_db, create_organization, get_organization,
    add_relationship, get_relationships, remove_relationship,
)


RELATIONSHIP_TYPES = [
    "competitor",
    "supplier",
    "customer",
    "distributor",
    "partner",
    "other",
]

PRIORITIES = ["high", "medium", "low"]


def cmd_list_orgs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM organizations ORDER BY id").fetchall()
    conn.close()

    if not rows:
        print("  (belum ada organization)")
        return

    print(f"\n  {'ID':>3}  {'Name':35} {'Sector':20} {'Tier':8}")
    print(f"  {'-'*3}  {'-'*35} {'-'*20} {'-'*8}")
    for r in rows:
        print(f"  {r['id']:>3}  {r['name'][:35]:35} "
              f"{(r['sector_slug'] or '-')[:20]:20} {r['size_tier'] or '-':8}")


def cmd_create_org():
    print("\n=== CREATE ORGANIZATION ===")
    name = input("  Nama perusahaan: ").strip()
    sector = input("  Sector slug (mis. consumer-non-cyclicals): ").strip()
    subsector = input("  Sub-sector slug (mis. food-beverage): ").strip()
    size = input("  Size tier (micro/small/medium/large): ").strip().lower()
    desc = input("  Deskripsi (opsional): ").strip()

    conn = get_conn()
    org_id = create_organization(conn, name, sector, subsector, size, desc)
    conn.close()
    print(f"\n  ✓ Organization created: id={org_id}, name='{name}'")


def cmd_add_relationships(org_id: int):
    conn = get_conn()
    org = get_organization(conn, org_id)
    if not org:
        print(f"  ✗ Org id={org_id} tidak ditemukan")
        conn.close()
        return

    print(f"\n=== ADD RELATIONSHIPS untuk '{org['name']}' ===")
    print("  Format: SYMBOL,type,priority")
    print("  Contoh: BBCA,competitor,high")
    print("  Ketik 'done' kalau selesai\n")

    while True:
        line = input("  > ").strip()
        if line.lower() in ("done", "exit", "quit", ""):
            break

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            print("  ✗ format salah, minimal SYMBOL,type")
            continue

        symbol = parts[0].upper()
        rel_type = parts[1].lower()
        priority = parts[2].lower() if len(parts) > 2 else "medium"

        if rel_type not in RELATIONSHIP_TYPES:
            print(f"  ✗ type harus salah satu: {RELATIONSHIP_TYPES}")
            continue
        if priority not in PRIORITIES:
            print(f"  ✗ priority harus salah satu: {PRIORITIES}")
            continue

        # Validasi company ada di DB
        c = conn.execute(
            "SELECT name FROM companies WHERE symbol = ?", [symbol]
        ).fetchone()
        if not c:
            print(f"  ✗ {symbol} belum ada di DB (ingest dulu)")
            continue

        added = add_relationship(conn, org_id, symbol, rel_type, priority)
        if added:
            print(f"  ✓ {symbol} ({c['name'][:30]}) → {rel_type} [{priority}]")
        else:
            print(f"  ⚠ {symbol} sudah pernah di-add (skip)")

    conn.close()


def cmd_show_relationships(org_id: int):
    conn = get_conn()
    org = get_organization(conn, org_id)
    if not org:
        print(f"  ✗ Org id={org_id} tidak ditemukan")
        conn.close()
        return

    print(f"\n=== '{org['name']}' — MONITORED COMPANIES ===")
    rels = get_relationships(conn, org_id)
    conn.close()

    if not rels:
        print("  (belum ada relationship)")
        return

    # Group by type
    by_type = {}
    for r in rels:
        by_type.setdefault(r["relationship_type"], []).append(r)

    for rel_type in RELATIONSHIP_TYPES:
        if rel_type not in by_type:
            continue
        items = by_type[rel_type]
        print(f"\n  {rel_type.upper()} ({len(items)})")
        for r in items:
            icon = "🔴" if r["priority"] == "high" else ("🟡" if r["priority"] == "medium" else "🟢")
            print(f"    {icon} {r['company_symbol']:6} {r['company_name'][:40]:40} "
                  f"[{r['priority']}]")


def cmd_remove(org_id: int, symbol: str):
    conn = get_conn()
    ok = remove_relationship(conn, org_id, symbol.upper())
    conn.close()
    if ok:
        print(f"  ✓ {symbol} dihapus dari monitoring")
    else:
        print(f"  ✗ {symbol} tidak ditemukan di monitoring")


def main():
    init_db()

    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python relationship_manager.py list")
        print("  python relationship_manager.py create")
        print("  python relationship_manager.py add <org_id>")
        print("  python relationship_manager.py show <org_id>")
        print("  python relationship_manager.py remove <org_id> <symbol>")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list_orgs()
    elif cmd == "create":
        cmd_create_org()
    elif cmd == "add" and len(sys.argv) >= 3:
        cmd_add_relationships(int(sys.argv[2]))
    elif cmd == "show" and len(sys.argv) >= 3:
        cmd_show_relationships(int(sys.argv[2]))
    elif cmd == "remove" and len(sys.argv) >= 4:
        cmd_remove(int(sys.argv[2]), sys.argv[3])
    else:
        print(f"  ✗ command tidak dikenal: {cmd}")


if __name__ == "__main__":
    main()