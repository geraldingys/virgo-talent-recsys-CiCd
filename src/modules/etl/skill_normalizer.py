# =============================================================
# skill_normalizer.py
# Modul ETL — Increment 2: Semantic Similarity
#
# Tanggung Jawab:
#   Menangani keragaman penulisan skill dari spreadsheet
#   sebelum data diteruskan ke validator dan Neo4j writer.
#
# Arsitektur tiga lapisan (sesuai pola NER Increment 1):
#   Lapisan 1 — Rule-based (alias map deterministik)
#   Lapisan 2 — Fuzzy matching (rapidfuzz, threshold ≥ 85)
#   Lapisan 3 — LLM fallback via Ollama [rekomendasi pengembangan]
#
# Penggunaan:
#   normalizer = SkillNormalizer(ontology_labels)
#   canonical, method = normalizer.normalize("Node JS")
#   # → ("Node.js", "alias")
#   # → ("Node.js", "fuzzy:92")
#   # → (None, "not_found") jika tidak ada yang cocok
#
# Referensi:
#   Sánchez, D. et al. (2012) Expert Systems with Applications
#   — normalisasi label adalah prasyarat akurasi IC computation
# =============================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger
import re

try:
    from rapidfuzz import process as rf_process, fuzz
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _RAPIDFUZZ_AVAILABLE = False
    logger.warning(
        "rapidfuzz tidak terinstal. Lapisan 2 (fuzzy) tidak aktif. "
        "Jalankan: pip install rapidfuzz"
    )


# =============================================================
# LAPISAN 1 — Alias Map Deterministik
# Divalidasi terhadap ontology/ttl/Data model v2.ttl (rdfs:label)
# beserta variasi penulisan umum di spreadsheet Indonesia.
#
# Kunci  : variasi penulisan (lowercase, tanpa spasi berlebih)
# Nilai  : rdfs:label kanonik sesuai ontologi
# =============================================================

_ALIAS_MAP: dict[str, str] = {
    ".net": ".NET Ecosystem",
    "dot net": ".NET Ecosystem",
    "dotnet": ".NET Ecosystem",
    "ai": "AI & Machine Learning",
    "ai/ml": "AI & Machine Learning",
    "artificial intelligence": "AI & Machine Learning",
    "machine learning": "AI & Machine Learning",
    "ml": "AI & Machine Learning",
    "ajax": "AJAX",
    "api": "API & Integration",
    "api doc": "API Documentation",
    "api documentation": "API Documentation",
    "postman doc": "API Documentation",
    "rest": "API Protocols & Standards",
    "rest api": "API Protocols & Standards",
    "restful": "API Protocols & Standards",
    "restful api": "API Protocols & Standards",
    "postman testing": "API Testing Tools",
    "asp net": "ASP.NET Core",
    "asp.net": "ASP.NET Core",
    "asp.net core": "ASP.NET Core",
    "aspnet": "ASP.NET Core",
    "asp.net mvc": "ASP.NET MVC",
    "amazon aws": "AWS",
    "amazon web services": "AWS",
    "aws": "AWS",
    "activity diagram": "Activity Diagram",
    "adobe illustrator": "Adobe Illustrator",
    "illustrator": "Adobe Illustrator",
    "adobe photoshop": "Adobe Photoshop",
    "photoshop": "Adobe Photoshop",
    "agile": "Agile",
    "android": "Android SDK",
    "java android": "Android SDK",
    "angular": "Angular",
    "angular js": "Angular",
    "angularjs": "Angular",
    "ansible": "Ansible",
    "ant design": "Ant Design",
    "antd": "Ant Design",
    "apache poi": "Apache POI",
    "poi": "Apache POI",
    "apollo": "Apollo",
    "appium": "Appium",
    "clean architecture": "Architecture Patterns",
    "mvc": "Architecture Patterns",
    "active mq": "ArtemisMQ",
    "activemq": "ArtemisMQ",
    "artemis": "ArtemisMQ",
    "artemis mq": "ArtemisMQ",
    "artemismq": "ArtemisMQ",
    "axios": "Axios",
    "azure data studio": "Azure Data Studio",
    "bdd": "BDD",
    "bloc": "BLoC",
    "brd": "BRD",
    "balsamiq": "Balsamiq",
    "bcrypt": "Bcrypt",
    "big query": "BigQuery",
    "bigquery": "BigQuery",
    "bizagi": "Bizagi",
    "biznet": "Biznet Cloud",
    "biznet cloud": "Biznet Cloud",
    "bootstrap": "Bootstrap",
    "bugzilla": "Bugzilla",
    "bull mq": "BullMQ",
    "bullmq": "BullMQ",
    "burp suite": "Burp Suite",
    "burpsuite": "Burp Suite",
    "c sharp": "C#",
    "c#": "C#",
    "csharp": "C#",
    "c++": "C++",
    "cpp": "C++",
    "ci cd": "CI/CD",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "camunda": "Camunda",
    "camunda bpmn": "Camunda",
    "canva": "Canva",
    "class diagram": "Class Diagram",
    "cloudflare": "Cloudflare",
    "ci": "CodeIgniter",
    "code igniter": "CodeIgniter",
    "codeigniter": "CodeIgniter",
    "confluence": "Confluence",
    "cucumber": "Cucumber",
    "cypress": "Cypress",
    "db diagram": "DBDiagram",
    "dbdiagram": "DBDiagram",
    "dbeaver": "DBeaver",
    "dfd": "DFD",
    "dart": "Dart",
    "design pattern": "Design Principles & OOP",
    "design patterns": "Design Principles & OOP",
    "oop": "Design Principles & OOP",
    "solid": "Design Principles & OOP",
    "dev ops": "DevOps & CI/CD Tooling",
    "devops": "DevOps & CI/CD Tooling",
    "django": "Django",
    "docker": "Docker",
    "docker hub": "Docker Hub",
    "dockerhub": "Docker Hub",
    "draw.io": "Draw.io",
    "drawio": "Draw.io",
    "erp next": "ERPNext",
    "erpnext": "ERPNext",
    "eslint": "ESLint",
    "eclipse": "Eclipse",
    "elastic search": "Elasticsearch",
    "elasticsearch": "Elasticsearch",
    "electron": "Electron.js",
    "electron.js": "Electron.js",
    "electronjs": "Electron.js",
    "e2e": "End-to-End (E2E) Testing",
    "end to end": "End-to-End (E2E) Testing",
    "entity relationship diagram": "Entity-Relationship Diagram",
    "entity-relationship": "Entity-Relationship Diagram",
    "entity-relationship diagram": "Entity-Relationship Diagram",
    "erd": "Entity-Relationship Diagram",
    "erd diagram": "Entity-Relationship Diagram",
    "excalidraw": "Excalidraw",
    "excelize": "Excel",
    "express": "Express.js",
    "express js": "Express.js",
    "express.js": "Express.js",
    "expressjs": "Express.js",
    "fsd": "FSD",
    "ftp": "FTP",
    "sftp": "FTP",
    "fast api": "FastAPI",
    "fastapi": "FastAPI",
    "go fiber": "Fiber",
    "gofiber": "Fiber",
    "figma": "Figma",
    "flask": "Flask",
    "flowchart": "Flowchart",
    "flutter": "Flutter",
    "formik": "Formik",
    "frappe": "Frappe",
    "frappe framework": "Frappe",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "gis": "GIS & Geospatial",
    "gorm": "GORM",
    "geopandas": "GeoPandas",
    "geo server": "GeoServer",
    "geoserver": "GeoServer",
    "gin": "Gin",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "gitlab ci": "GitLab CI",
    "gitea": "Gitea",
    "go": "Go",
    "go lang": "Go",
    "golang": "Go",
    "go router": "Go Ecosystem",
    "gorouter": "Go Ecosystem",
    "google analytics": "Google Analytics",
    "google docs": "Google Docs",
    "google earth engine": "Google Earth Engine",
    "google sheets": "Google Sheets",
    "graph ql": "GraphQL",
    "graphql": "GraphQL",
    "gulp": "Gulp.js",
    "gulp.js": "Gulp.js",
    "hl7": "HL7",
    "handlebars": "Handlebars",
    "harbor": "Harbor",
    "hibernate": "Hibernate",
    "hibernate orm": "Hibernate",
    "husky": "Husky",
    "inertia": "Inertia.js",
    "inertiajs": "Inertia.js",
    "insomnia": "Insomnia",
    "intellij": "IntelliJ IDEA",
    "intellij idea": "IntelliJ IDEA",
    "jira": "JIRA",
    "j meter": "JMeter",
    "jmeter": "JMeter",
    "j unit": "JUnit",
    "junit": "JUnit",
    "junit5": "JUnit",
    "xunit": "JUnit",
    "json web token": "JWT",
    "jwt": "JWT",
    "jackson": "Jackson",
    "jaeger": "Jaeger",
    "jaeger tracing": "Jaeger",
    "jakarta ee": "Jakarta EE",
    "jasper": "JasperReports",
    "jasperreports": "JasperReports",
    "java": "Java",
    "javalang": "Java",
    "java swing": "Java Swing",
    "swing": "Java Swing",
    "java fx": "JavaFX",
    "javafx": "JavaFX",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "jenkins": "Jenkins",
    "jest": "Jest",
    "jetpack compose": "Jetpack Compose",
    "joi": "Joi",
    "jumpserver": "Jumpserver",
    "kafka": "Kafka",
    "kanban": "Kanban",
    "katalon": "Katalon",
    "dojo": "Kendo UI",
    "dojoui": "Kendo UI",
    "kendo": "Kendo UI",
    "kendo ui": "Kendo UI",
    "kibana": "Kibana",
    "kotlin": "Kotlin",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "ldap": "LDAP",
    "chatgpt": "LLM",
    "gemini": "LLM",
    "gemini/gpt": "LLM",
    "gpt": "LLM",
    "openai": "LLM",
    "laravel": "Laravel",
    "laravel lumen": "Laravel Lumen",
    "lumen": "Laravel Lumen",
    "delphi": "Lazarus",
    "lazarus": "Lazarus",
    "pascal": "Lazarus",
    "leaflet": "Leaflet",
    "liquibase": "Liquibase",
    "lombok": "Lombok",
    "looker": "Looker Studio",
    "looker studio": "Looker Studio",
    "mqtt": "MQTT",
    "mantis": "Mantis",
    "maria db": "MariaDB",
    "mariadb": "MariaDB",
    "material ui": "Material UI",
    "materialui": "Material UI",
    "mui": "Material UI",
    "gradle": "Maven",
    "maven": "Maven",
    "micro services": "Microservices",
    "microservices": "Microservices",
    "azure": "Microsoft Azure",
    "microsoft azure": "Microsoft Azure",
    "minio": "MinIO",
    "miro": "Miro",
    "mockito": "Mockito",
    "mapstruct": "ModelMapper",
    "modelmapper": "ModelMapper",
    "mongo": "MongoDB",
    "mongo db": "MongoDB",
    "mongodb": "MongoDB",
    "mongodb compass": "MongoDB Compass",
    "moodle": "Moodle",
    "my batis": "MyBatis",
    "mybatis": "MyBatis",
    "my sql": "MySQL",
    "my-sql": "MySQL",
    "mysql": "MySQL",
    "nginx": "NGINX",
    "ngix": "NGINX",
    "navicat": "Navicat",
    "nest js": "NestJS",
    "nest.js": "NestJS",
    "nestjs": "NestJS",
    "next": "Next.js",
    "next js": "Next.js",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "nightwatch": "Nightwatch.js",
    "node": "Node.js",
    "node js": "Node.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "nodemailer": "Nodemailer",
    "num py": "NumPy",
    "numpy": "NumPy",
    "nuxt": "Nuxt.js",
    "nuxt js": "Nuxt.js",
    "nuxt.js": "Nuxt.js",
    "nuxtjs": "Nuxt.js",
    "okd": "OKD",
    "owasp zap": "OWASP ZAP",
    "zap": "OWASP ZAP",
    "openlayers": "OpenLayers",
    "openshift": "OpenShift",
    "oracle": "Oracle Database",
    "oracle database": "Oracle Database",
    "oracle db": "Oracle Database",
    "outsystems": "OutSystems",
    "pgadmin": "PGAdmin",
    "php": "PHP",
    "phpmyadmin": "PHPMyAdmin",
    "pandas": "Pandas",
    "pinia": "Pinia",
    "plant uml": "PlantUML",
    "plantuml": "PlantUML",
    "playwright": "Playwright",
    "postgis": "PostGIS",
    "postgre": "PostgreSQL",
    "postgre sql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "postman": "Postman",
    "power bi": "Power Apps",
    "powerbi": "Power Apps",
    "power automate": "Power Automate",
    "powerautomate": "Power Automate",
    "power designer": "PowerDesigner",
    "prettier": "Prettier",
    "prime ng": "PrimeNG",
    "primeng": "PrimeNG",
    "prisma orm": "Prisma",
    "proto buf": "Protobuf",
    "protobuf": "Protobuf",
    "pyspark": "PySpark",
    "py torch": "PyTorch",
    "pytorch": "PyTorch",
    "python": "Python",
    "qgis": "QGIS",
    "java quarkus": "Quarkus",
    "quarkus": "Quarkus",
    "rpa": "RPA",
    "rabbit mq": "RabbitMQ",
    "rabbitmq": "RabbitMQ",
    "context api": "React Context API",
    "react context": "React Context API",
    "react native": "React Native",
    "reactnative": "React Native",
    "react": "React.js",
    "react js": "React.js",
    "react.js": "React.js",
    "reactjs": "React.js",
    "redis": "Redis",
    "redux": "Redux",
    "report builder": "Report Builder",
    "ruby": "Ruby",
    "rails": "Ruby on Rails",
    "ror": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "s3": "S3 Browser",
    "s3 browser": "S3 Browser",
    "sql lite": "SQL",
    "sqlite": "SQL",
    "microsoft sql server": "SQL Server",
    "ms sql": "SQL Server",
    "ms sql server": "SQL Server",
    "mssql": "SQL Server",
    "mssql server": "SQL Server",
    "sql server": "SQL Server",
    "sqlalchemy": "SQLAlchemy",
    "sso": "SSO",
    "scala": "Scala",
    "scikit learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "scrum": "Scrum",
    "selenium": "Selenium",
    "sequelize": "Sequelize",
    "sequence diagram": "Sequence Diagram",
    "service studio": "Service Studio",
    "signal r": "SignalR",
    "signalr": "SignalR",
    "smartsheet": "Smartsheet",
    "snowflake": "Snowflake",
    "solace": "Solace",
    "sonar qube": "SonarQube",
    "sonarqube": "SonarQube",
    "spring framework": "Spring",
    "spring": "Spring Boot",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    "struts": "Struts",
    "apache superset": "Superset",
    "superset": "Superset",
    "svelte": "Svelte",
    "open api": "Swagger",
    "openapi": "Swagger",
    "swagger": "Swagger",
    "swag": "Swaggo",
    "swaggo": "Swaggo",
    "tailwind": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "talend": "Talend",
    "react query": "TanStack Query",
    "tanstack query": "TanStack Query",
    "termius": "Termius",
    "terraform": "Terraform",
    "testrail": "TestRail",
    "trello": "Trello",
    "trivy": "Trivy",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "uml": "UML Diagrams",
    "ubuntu": "Ubuntu",
    "uipath": "UiPath",
    "unit test": "Unit & Integration Testing",
    "unit testing": "Unit & Integration Testing",
    "use case": "Use Case Diagram",
    "use case diagram": "Use Case Diagram",
    "vb script": "VBScript",
    "vbscript": "VBScript",
    "virtual machine": "VM",
    "vm": "VM",
    "vpn": "VPN",
    "vercel": "Vercel",
    "visual studio": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vite": "Vite",
    "vue": "Vue.js",
    "vue js": "Vue.js",
    "vue.js": "Vue.js",
    "vuejs": "Vue.js",
    "vuetify": "Vuetify",
    "web3": "Web3.js",
    "web3.js": "Web3.js",
    "web socket": "WebSocket",
    "websocket": "WebSocket",
    "wdio": "WebdriverIO",
    "webdriverio": "WebdriverIO",
    "webpack": "Webpack",
    "prototype": "Wireframing & Prototyping",
    "prototyping": "Wireframing & Prototyping",
    "wireframe": "Wireframing & Prototyping",
    "wireframing": "Wireframing & Prototyping",
    "xampp": "XAMPP",
    "xray": "Xray",
    "yaml": "YAML",
    "yii": "Yii",
    "yup": "Yup",
    "zeplin": "Zeplin",
    "zod": "Zod",
    "zookeeper": "Zookeeper",
    "zustand": "Zustand",
    "crypto js": "crypto.js",
    "crypto.js": "crypto.js",
    "d3": "d3.js",
    "d3.js": "d3.js",
    "d3js": "d3.js",
    "grpc": "gRPC",
    "j query": "jQuery",
    "jquery": "jQuery",
    "n8n": "n8n",
    "shadcn": "shadcn/ui",
    "shadcn ui": "shadcn/ui",
}


# =============================================================
# Kelas utama
# =============================================================

@dataclass
class NormalizeResult:
    original    : str
    canonical   : Optional[str]   # label kanonik dari ontologi
    method      : str             # "exact" | "alias" | "fuzzy:NN" | "not_found"
    confidence  : float           # 1.0 = exact/alias, 0.0-1.0 = fuzzy score


class SkillNormalizer:
    """
    Menormalisasi label skill dari spreadsheet ke label kanonik ontologi.

    Lapisan 1 — Alias map deterministik (cepat, tanpa library).
    Lapisan 2 — Fuzzy matching via rapidfuzz (threshold ≥ 85).

    Parameters
    ----------
    ontology_labels : list[str]
        Semua rdfs:label dari ontologi — digunakan oleh lapisan fuzzy.
        Ambil via: [node.label for node in skill_graph.all_nodes()]
    fuzzy_threshold : int
        Threshold minimum skor fuzzy (0-100). Default 85.
    """

    def __init__(
        self,
        ontology_labels : list[str],
        fuzzy_threshold : int = 85,
    ) -> None:
        self._ontology_labels = ontology_labels
        self._threshold       = fuzzy_threshold
        self._fuzzy_available = _RAPIDFUZZ_AVAILABLE

        # Bangun lookup alias: key lowercase → canonical
        self._alias_lookup = {k.lower(): v for k, v in _ALIAS_MAP.items()}

        # Tambahkan mapping otomatis untuk "level-2" labels yang mengandung
        # pemisah seperti '&', '/', ',', ';', 'and' atau '|' sehingga setiap
        # komponen tunggal juga akan map ke label kanonik.
        # Contoh: 'AI & Machine Learning' → 'ai' -> 'AI & Machine Learning',
        #                         'machine learning' -> 'AI & Machine Learning'
        seps_pattern = re.compile(r"\s*(?:&|/|,|;|and|\|)\s*", flags=re.IGNORECASE)
        for label in self._ontology_labels:
            # hanya pertimbangkan label non-empty
            if not label or not isinstance(label, str):
                continue
            parts = seps_pattern.split(label)
            # jika ada lebih dari satu bagian, tambahkan setiap bagian ke lookup
            if len(parts) > 1:
                for p in parts:
                    part = p.strip().lower()
                    if not part:
                        continue
                    # jika belum ada mapping, tambahkan
                    if part not in self._alias_lookup:
                        self._alias_lookup[part] = label

    def normalize(self, raw_label: str) -> NormalizeResult:
        """
        Menormalisasi satu label skill mentah dari spreadsheet.

        Urutan pencarian:
        1. Exact match terhadap label ontologi (case-insensitive)
        2. Alias map deterministik
        3. Fuzzy matching (jika rapidfuzz tersedia)
        4. not_found jika semua lapisan gagal

        Parameters
        ----------
        raw_label : str
            Label skill mentah dari kolom Teknologi spreadsheet.

        Returns
        -------
        NormalizeResult
        """
        cleaned = raw_label.strip()
        lower   = cleaned.lower()

        # ── Lapisan 0: Exact match ke label ontologi ──────
        for label in self._ontology_labels:
            if label.lower() == lower:
                return NormalizeResult(
                    original   = cleaned,
                    canonical  = label,
                    method     = "exact",
                    confidence = 1.0,
                )

        # ── Lapisan 1: Alias map ──────────────────────────
        if lower in self._alias_lookup:
            canonical = self._alias_lookup[lower]
            return NormalizeResult(
                original   = cleaned,
                canonical  = canonical,
                method     = "alias",
                confidence = 1.0,
            )

        # ── Lapisan 2: Fuzzy matching ─────────────────────
        if self._fuzzy_available and self._ontology_labels:
            result = rf_process.extractOne(
                cleaned,
                self._ontology_labels,
                scorer    = fuzz.token_sort_ratio,
                score_cutoff = self._threshold,
            )
            if result is not None:
                match_label, score, _ = result
                logger.info(
                    f"SkillNormalizer [fuzzy]: '{cleaned}' → '{match_label}' "
                    f"(score={score})"
                )
                return NormalizeResult(
                    original   = cleaned,
                    canonical  = match_label,
                    method     = f"fuzzy:{score}",
                    confidence = score / 100.0,
                )

        # ── Tidak ditemukan ───────────────────────────────
        logger.warning(
            f"SkillNormalizer: '{cleaned}' tidak dapat dinormalisasi. "
            f"Skill akan dilewati."
        )
        return NormalizeResult(
            original   = cleaned,
            canonical  = None,
            method     = "not_found",
            confidence = 0.0,
        )

    def normalize_batch(self, raw_labels: list[str]) -> list[NormalizeResult]:
        """
        Menormalisasi seluruh daftar skill sekaligus.
        Mengembalikan hasil untuk semua label termasuk yang not_found.
        """
        return [self.normalize(label) for label in raw_labels]

    def get_canonical_labels(self, raw_labels: list[str]) -> list[str]:
        """
        Shortcut: mengembalikan hanya label kanonik yang berhasil dinormalisasi.
        Label yang not_found dibuang secara diam-diam (sudah di-log sebagai warning).
        """
        results = self.normalize_batch(raw_labels)
        return [r.canonical for r in results if r.canonical is not None]
