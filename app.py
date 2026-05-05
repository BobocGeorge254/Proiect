"""
Flask app pentru Sistemul Integrat de Gestiune Medicala (Distribuit).

UI modern + REST API care expune cele 4 noduri ale bazei de date,
formele de transparenta, sincronizarea nomenclatoarelor, validarile
distribuite si raportul OLAP cu 3 strategii de optimizare.
"""

from __future__ import annotations

from datetime import datetime
from flask import Flask, jsonify, render_template, request, send_from_directory

import database as db


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    db.init_schemas()
    if db.seed_if_empty():
        app.logger.info("Demo data seeded successfully.")

    @app.route("/")
    def index():
        return render_template("index.html")

    # ---- Status retea ----------------------------------------------------
    @app.get("/api/network")
    def api_network():
        nodes = []
        for code, info in db.NODES.items():
            n = {
                "code": code,
                "user": info["user"],
                "label": info["label"],
                "regiune": info.get("regiune"),
                "tables": {},
            }
            tables = ["SECTIE", "SPECIALIZARE", "DIAGNOSTIC", "TRATAMENT",
                      "MEDIC_OP", "MEDIC_SPECIALIZARI", "MEDIC_SECTII"]
            if code != "S1":
                tables += ["PACIENTI_LOCAL", "PROGRAMARE_LOCAL", "FACTURA_LOCAL", "PROG_DIAG_LOCAL"]
            else:
                tables += ["MEDIC_HR", "CATALOG_GLOBAL"]
            for t in tables:
                try:
                    r = db.query(code, f"SELECT COUNT(*) AS c FROM {t}", kind="STATUS")
                    n["tables"][t] = r[0]["c"]
                except Exception:
                    n["tables"][t] = None
            nodes.append(n)
        return jsonify({"nodes": nodes})

    # ---- Catalog generic ------------------------------------------------
    @app.get("/api/node/<node>/<table>")
    def api_node_table(node: str, table: str):
        node = node.upper()
        table = table.upper()
        if node not in db.NODES:
            return jsonify({"error": "Nod necunoscut"}), 400
        allowed = {"DIAGNOSTIC", "TRATAMENT", "SPECIALIZARE", "SECTIE", "MEDIC_OP"}
        if table not in allowed:
            return jsonify({"error": "Tabel nepermis"}), 400
        try:
            rows = [dict(r) for r in db.query(node, f"SELECT * FROM {table} ORDER BY 1",
                                              kind=f"NODE READ @ {node}")]
            return jsonify({"node": node, "rows": rows})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/api/catalog/<table>")
    def api_catalog(table: str):
        table = table.upper()
        whitelist = {
            "DIAGNOSTIC": "S1",
            "TRATAMENT": "S1",
            "SPECIALIZARE": "S1",
            "SECTIE": "S1",
        }
        if table not in whitelist:
            return jsonify({"error": "Tabel necunoscut"}), 400
        rows = [dict(r) for r in db.query(whitelist[table], f"SELECT * FROM {table} ORDER BY 1",
                                          kind="CATALOG READ")]
        return jsonify({"rows": rows})

    # ---- Vederi globale (transparenta) ----------------------------------
    @app.get("/api/global/pacienti")
    def api_global_pacienti():
        node = request.args.get("node")
        rows = db.view_pacienti_complet(filter_node=node)
        return jsonify({"rows": rows})

    @app.get("/api/global/programari")
    def api_global_programari():
        return jsonify({"rows": db.view_programare_complet()})

    @app.get("/api/global/facturi")
    def api_global_facturi():
        return jsonify({"rows": db.view_factura_complet()})

    @app.get("/api/global/medici")
    def api_global_medici():
        return jsonify({"rows": db.view_medic_complet()})

    # ---- Inserari (cu transparenta + integritate distribuita) -----------
    @app.post("/api/pacient")
    def api_post_pacient():
        d = request.json or {}
        try:
            pid = db.insert_pacient(
                nume=d["nume"], prenume=d["prenume"], cnp=d["cnp"],
                data_nasterii=d["data_nasterii"], gen=d["gen"], regiune=d["regiune"],
            )
            return jsonify({"ok": True, "id_pacient": pid,
                             "node": db.REGION_TO_NODE[d["regiune"]]})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/programare")
    def api_post_programare():
        d = request.json or {}
        try:
            pid = db.insert_programare(
                id_pacient=int(d["id_pacient"]),
                id_medic=int(d["id_medic"]),
                id_tratament=int(d["id_tratament"]) if d.get("id_tratament") else None,
                data_ora=d["data_ora"],
                durata_min=int(d.get("durata_min") or 30),
                status=d.get("status") or "Programat",
                target_node=d.get("target_node"),
            )
            return jsonify({"ok": True, "id_programare": pid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/factura")
    def api_post_factura():
        d = request.json or {}
        try:
            fid = db.insert_factura(
                id_programare=int(d["id_programare"]),
                suma=float(d["suma"]),
                status_plata=d["status_plata"],
                data_emitere=d.get("data_emitere"),
            )
            return jsonify({"ok": True, "id_factura": fid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/prog_diag")
    def api_post_prog_diag():
        d = request.json or {}
        try:
            pdid = db.insert_prog_diag(
                id_programare=int(d["id_programare"]),
                id_diagnostic=int(d["id_diagnostic"]),
                este_principal=int(d.get("este_principal") or 0),
            )
            return jsonify({"ok": True, "id_prog_diag": pdid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/medic")
    def api_post_medic():
        d = request.json or {}
        try:
            id_medic = int(d["id_medic"])
            db.insert_medic(
                id_medic=id_medic, nume=d["nume"], prenume=d["prenume"],
                cod_parafa=d["cod_parafa"], data_angajarii=d["data_angajarii"],
                salariu=float(d["salariu"]),
            )
            return jsonify({"ok": True, "id_medic": id_medic})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/medic/<int:id_medic>/salariu")
    def api_post_salariu(id_medic: int):
        d = request.json or {}
        try:
            db.update_salariu(id_medic, float(d["salariu"]))
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ---- Replicare (master = SUD) pentru DIAGNOSTIC ----------------------
    @app.post("/api/diagnostic")
    def api_post_diagnostic():
        d = request.json or {}
        try:
            new_id = int(d.get("id_diagnostic") or
                          (max([r["id_diagnostic"] for r in
                                db.query("S1", "SELECT id_diagnostic FROM DIAGNOSTIC",
                                         kind="MAX SCAN")] or [0]) + 1))
            db.replicate_to_all(
                "DIAGNOSTIC",
                ("id_diagnostic", "cod_boala", "nume", "severitate"),
                (new_id, d["cod_boala"], d["nume"], d["severitate"]),
                master_node="S2",
            )
            return jsonify({"ok": True, "id_diagnostic": new_id})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.put("/api/diagnostic/<int:id_diagnostic>")
    def api_put_diagnostic(id_diagnostic: int):
        d = request.json or {}
        try:
            db.update_replicated(
                "DIAGNOSTIC",
                "cod_boala = ?, nume = ?, severitate = ?",
                "id_diagnostic = ?",
                (d["cod_boala"], d["nume"], d["severitate"], id_diagnostic),
            )
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.delete("/api/diagnostic/<int:id_diagnostic>")
    def api_delete_diagnostic(id_diagnostic: int):
        try:
            db.delete_replicated("DIAGNOSTIC", "id_diagnostic = ?", (id_diagnostic,))
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ---- Raport OLAP (3 strategii) --------------------------------------
    @app.post("/api/report/diabet")
    def api_report_diabet():
        d = request.json or {}
        diag = d.get("diagnostic_name") or "Diabet"
        year = int(d["year"]) if d.get("year") else None
        strategy = d.get("strategy") or "all"

        results = {}
        if strategy in ("all", "sequential"):
            results["sequential"] = db.report_diabet_sequential(diag, year)
        if strategy in ("all", "hash"):
            results["hash"] = db.report_diabet_hash_join(diag, year)
        if strategy in ("all", "parallel"):
            results["parallel"] = db.report_diabet_parallel_semijoin(diag, year)

        return jsonify({"ok": True, "diagnostic": diag, "year": year, "results": results})

    # ---- Log interogari -------------------------------------------------
    @app.get("/api/log")
    def api_log():
        limit = int(request.args.get("limit", 60))
        return jsonify({"entries": db.QUERY_LOG[-limit:][::-1]})

    @app.post("/api/log/clear")
    def api_log_clear():
        db.QUERY_LOG.clear()
        return jsonify({"ok": True})

    # ---- Reset demo -----------------------------------------------------
    @app.post("/api/reset")
    def api_reset():
        import os
        db.close_all()
        for info in db.NODES.values():
            path = os.path.join(db.DATA_DIR, info["file"])
            if os.path.exists(path):
                os.remove(path)
            for ext in ("-wal", "-shm"):
                if os.path.exists(path + ext):
                    os.remove(path + ext)
        db.QUERY_LOG.clear()
        db.init_schemas()
        db.seed_if_empty()
        return jsonify({"ok": True})

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "ts": datetime.now().isoformat()})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
