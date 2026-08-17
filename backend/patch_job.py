lines = open('app/services/jar_analyser/job.py', encoding='utf-8').readlines()

new_block = '''        # Frontend installers — Node.js/UI, no Java bytecode
        if sr.jar_type == "frontend_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import FrontendAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    fa = FrontendAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "frontend": {
                        "package_name": fa.package_name,
                        "package_version": fa.package_version,
                        "description": fa.description,
                        "framework": fa.framework,
                        "app_version": fa.app_version,
                        "node_scripts": fa.node_scripts,
                        "dependencies": fa.dependencies,
                        "dev_dependencies": fa.dev_dependencies,
                        "server_entry_points": fa.server_entry_points,
                        "api_urls": fa.api_urls,
                    }
                })
                for rf in fa.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "yaml" if rf["filename"].endswith((".yml", ".yaml")) else "json",
                        "profile": None,
                        "content": rf["content"],
                        "key_count": len(fa.api_urls),
                        "encrypted_count": 0,
                        "placeholder_count": sum(1 for u in fa.api_urls if "${" in u.get("value", "")),
                        "ssl_key_count": 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [{"key": u["key"], "value": u["value"],
                                   "is_encrypted": False, "is_placeholder": "${" in u["value"],
                                   "category": "other"} for u in fa.api_urls],
                    })
            except Exception as e:
                sr.warnings.append(f"Frontend analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

        # Nginx config-only installers
        if sr.jar_type == "nginx_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import NginxAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    na = NginxAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "nginx": {
                        "upstreams": [{"name": u.name, "servers": u.servers, "keepalive": u.keepalive}
                                       for u in na.upstreams],
                        "ha_upstreams": [{"name": u.name, "servers": u.servers}
                                          for u in na.ha_upstreams],
                        "server_blocks": [{"listen_ports": s.listen_ports, "server_names": s.server_names,
                                            "ssl": s.ssl, "locations": s.locations}
                                           for s in na.server_blocks],
                        "service_dependencies": na.service_dependencies,
                    }
                })
                for rf in na.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "conf",
                        "profile": "ha" if rf["filename"].endswith(".ha") else None,
                        "content": rf["content"],
                        "key_count": len(na.upstreams),
                        "encrypted_count": 0,
                        "placeholder_count": rf["content"].count("${"),
                        "ssl_key_count": 1 if "ssl" in rf["content"].lower() else 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [{"key": f"upstream.{u.name}", "value": ", ".join(u.servers),
                                   "is_encrypted": False, "is_placeholder": any("${" in s for s in u.servers),
                                   "category": "other"} for u in na.upstreams],
                    })
            except Exception as e:
                sr.warnings.append(f"Nginx analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

        # Monitoring config-only installers (Grafana / Prometheus)
        if sr.jar_type == "monitoring_installer":
            try:
                from app.services.jar_analyser.bundle_analyser import MonitoringAnalyser
                with __import__('zipfile').ZipFile(jar_path) as zf:
                    ma = MonitoringAnalyser.from_jar(zf)
                sr.installer_metadata.update({
                    "monitoring": {
                        "grafana_dashboards": [{"filename": d.filename, "title": d.title,
                                                 "panel_count": d.panel_count, "panel_titles": d.panel_titles}
                                                for d in ma.grafana_dashboards],
                        "grafana_datasources": [{"name": ds.name, "type": ds.type, "url": ds.url}
                                                 for ds in ma.grafana_datasources],
                        "grafana_ini": ma.grafana_ini,
                        "prometheus_jobs": [{"job_name": j.job_name, "metrics_path": j.metrics_path,
                                              "targets": j.targets, "scheme": j.scheme,
                                              "has_auth": j.has_auth, "has_tls": j.has_tls}
                                             for j in ma.prometheus_jobs],
                    }
                })
                for rf in ma.raw_files:
                    sr.config_files.append({
                        "filename": rf["filename"],
                        "path_in_jar": rf["path"],
                        "file_type": "yaml" if rf["filename"].endswith((".yml", ".yaml")) else
                                     "ini" if rf["filename"].endswith(".ini") else "json",
                        "profile": None,
                        "content": rf["content"],
                        "key_count": 0,
                        "encrypted_count": 0,
                        "placeholder_count": 0,
                        "ssl_key_count": 1 if "tls" in rf["content"].lower() or "ssl" in rf["content"].lower() else 0,
                        "db_key_count": 0,
                        "mq_key_count": 0,
                        "keys": [],
                    })
            except Exception as e:
                sr.warnings.append(f"Monitoring analysis failed: {e}")
            sr.duration_ms = int((time.monotonic() - t0) * 1000)
            return sr

'''

# Replace lines 384-412 (0-indexed: 383-411) with new block
result = lines[:383] + [new_block] + lines[412:]
open('app/services/jar_analyser/job.py', 'w', encoding='utf-8').writelines(result)
print("Done, lines written:", len(result))
