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
# Dibangun dari seluruh rdfs:label di Data_model_v2.ttl
# beserta variasi penulisan umum di spreadsheet Indonesia.
#
# Kunci  : variasi penulisan (lowercase, tanpa spasi berlebih)
# Nilai  : rdfs:label kanonik sesuai ontologi
# =============================================================

_ALIAS_MAP: dict[str, str] = {

    # ── AI & Machine Learning ──────────────────────────────
    "ai"                        : "AI & Machine Learning",
    "machine learning"          : "AI & Machine Learning",
    "ml"                        : "AI & Machine Learning",
    "artificial intelligence"   : "AI & Machine Learning",
    "ai/ml"                     : "AI & Machine Learning",
    "gemini"                    : "Gemini/GPT",
    "chatgpt"                   : "Gemini/GPT",
    "gpt"                       : "Gemini/GPT",
    "openai"                    : "Gemini/GPT",

    # ── API & Integration ──────────────────────────────────
    "api"                       : "API & Integration",
    "rest api"                  : "API Protocols & Standards",
    "restful"                   : "API Protocols & Standards",
    "restful api"               : "API Protocols & Standards",
    "rest"                      : "API Protocols & Standards",
    "graphql"                   : "GraphQL",
    "graph ql"                  : "GraphQL",
    "grpc"                      : "gRPC",
    "websocket"                 : "WebSocket",
    "web socket"                : "WebSocket",
    "jwt"                       : "JSON Web Token (JWT)",
    "json web token"            : "JSON Web Token (JWT)",
    "apollo"                    : "Apollo",
    "axios"                     : "Axios",
    "ajax"                      : "AJAX",

    # ── Cloud & Infrastructure ─────────────────────────────
    "aws"                       : "AWS",
    "amazon web services"       : "AWS",
    "gcp"                       : "Google Cloud Platform (GCP)",
    "google cloud"              : "Google Cloud Platform (GCP)",
    "google cloud platform"     : "Google Cloud Platform (GCP)",
    "azure"                     : "Microsoft Azure",
    "microsoft azure"           : "Microsoft Azure",
    "azure data studio"         : "Azure Data Studio",
    "bigquery"                  : "BigQuery",
    "big query"                 : "BigQuery",
    "biznet"                    : "Biznet Cloud",
    "cloudflare"                : "Cloudflare",
    "docker"                    : "Docker",
    "docker hub"                : "Docker Hub",
    "dockerhub"                 : "Docker Hub",
    "kubernetes"                : "Kubernetes (K8s)",
    "k8s"                       : "Kubernetes (K8s)",
    "ansible"                   : "Ansible",
    "vm"                        : "VM (Virtual Machine)",
    "virtual machine"           : "VM (Virtual Machine)",

    # ── Databases & Data Stores ────────────────────────────
    "mysql"                     : "MySQL",
    "my sql"                    : "MySQL",
    "my-sql"                    : "MySQL",
    "mariadb"                   : "MariaDB",
    "maria db"                  : "MariaDB",
    "postgresql"                : "PostgreSQL",
    "postgres"                  : "PostgreSQL",
    "postgre sql"               : "PostgreSQL",
    "postgre"                   : "PostgreSQL",
    "oracle"                    : "Oracle DB",
    "oracle db"                 : "Oracle DB",
    "oracle database"           : "Oracle DB",
    "mssql"                     : "Microsoft SQL Server",
    "sql server"                : "Microsoft SQL Server",
    "microsoft sql server"      : "Microsoft SQL Server",
    "ms sql"                    : "Microsoft SQL Server",
    "sqlite"                    : "SQLite",
    "sql lite"                  : "SQLite",
    "mongodb"                   : "MongoDB",
    "mongo"                     : "MongoDB",
    "mongo db"                  : "MongoDB",
    "redis"                     : "Redis",
    "elasticsearch"             : "Elasticsearch",
    "elastic search"            : "Elasticsearch",
    "cassandra"                 : "Cassandra",
    "hbase"                     : "HBase",
    "h base"                    : "HBase",
    "dbeaver"                   : "DBeaver",
    "erd"                       : "ERD",
    "entity relationship diagram": "ERD",

    # ── Development Tools & IDEs ───────────────────────────
    "vscode"                    : "Visual Studio Code",
    "vs code"                   : "Visual Studio Code",
    "visual studio code"        : "Visual Studio Code",
    "visual studio"             : "Visual Studio Code",
    "intellij"                  : "IntelliJ IDEA",
    "intellij idea"             : "IntelliJ IDEA",
    "eclipse"                   : "Eclipse",
    "netbeans"                  : "NetBeans",
    "git"                       : "Git",
    "github"                    : "GitHub",
    "gitlab"                    : "GitLab",
    "gitlab ci"                 : "GitLab CI",
    "gitea"                     : "Gitea",
    "jenkins"                   : "Jenkins",
    "eslint"                    : "ESLint",
    "yaml"                      : "YAML",
    "xampp"                     : "XAMPP",
    "postman"                   : "Postman",

    # ── DevOps & CI/CD ─────────────────────────────────────
    "cicd"                      : "CI/CD",
    "ci cd"                     : "CI/CD",
    "ci/cd"                     : "CI/CD",
    "devops"                    : "DevOps & CI/CD Tooling",
    "dev ops"                   : "DevOps & CI/CD Tooling",
    "zookeeper"                 : "Zookeeper",
    "jumpserver"                : "Jumpserver",
    "kibana"                    : "Kibana",
    "jaeger"                    : "Jaeger",
    "elasticjob"                : "ElasticJob",
    "elastic job"               : "ElasticJob",

    # ── Frameworks & Libraries — Frontend ──────────────────
    "react"                     : "React.js",
    "reactjs"                   : "React.js",
    "react js"                  : "React.js",
    "react.js"                  : "React.js",
    "vue"                       : "Vue.js",
    "vuejs"                     : "Vue.js",
    "vue js"                    : "Vue.js",
    "vue.js"                    : "Vue.js",
    "angular"                   : "Angular",
    "angularjs"                 : "Angular",
    "angular js"                : "Angular",
    "next"                      : "Next.js",
    "nextjs"                    : "Next.js",
    "next js"                   : "Next.js",
    "next.js"                   : "Next.js",
    "nuxt"                      : "Nuxt.js",
    "nuxtjs"                    : "Nuxt.js",
    "nuxt js"                   : "Nuxt.js",
    "nuxt.js"                   : "Nuxt.js",
    "svelte"                    : "Svelte",
    "jquery"                    : "jQuery",
    "j query"                   : "jQuery",
    "bootstrap"                 : "Bootstrap",
    "tailwind"                  : "Tailwind CSS",
    "tailwind css"              : "Tailwind CSS",
    "tailwindcss"               : "Tailwind CSS",
    "antd"                      : "Ant Design",
    "ant design"                : "Ant Design",
    "material ui"               : "Material UI (MUI)",
    "materialui"                : "Material UI (MUI)",
    "mui"                       : "Material UI (MUI)",
    "vuetify"                   : "Vuetify",
    "kendo"                     : "Kendo UI",
    "kendo ui"                  : "Kendo UI",
    "handlebars"                : "Handlebars",
    "formik"                    : "Formik",
    "zod"                       : "Zod",
    "flatpickr"                 : "Flatpickr",
    "context api"               : "Context API",
    "zustand"                   : "Zustand",
    "redux"                     : "Redux",
    "webpack"                   : "Webpack",
    "vite"                      : "Vite",
    "gulp"                      : "Gulp.js",
    "gulp.js"                   : "Gulp.js",
    "electron"                  : "Electron.js",
    "electron.js"               : "Electron.js",
    "electronjs"                : "Electron.js",
    "dojoui"                    : "Dojo UI",
    "dojo"                      : "Dojo UI",

    # ── Frameworks & Libraries — Backend ───────────────────
    "nodejs"                    : "Node.js",
    "node js"                   : "Node.js",
    "node.js"                   : "Node.js",
    "node"                      : "Node.js",
    "express"                   : "Express.js",
    "expressjs"                 : "Express.js",
    "express js"                : "Express.js",
    "express.js"                : "Express.js",
    "nestjs"                    : "NestJS",
    "nest js"                   : "NestJS",
    "nest.js"                   : "NestJS",
    "fastapi"                   : "FastAPI",
    "fast api"                  : "FastAPI",
    "django"                    : "Django",
    "flask"                     : "Flask",
    "laravel"                   : "Laravel",
    "lumen"                     : "Laravel Lumen",
    "laravel lumen"             : "Laravel Lumen",
    "codeigniter"               : "CodeIgniter",
    "code igniter"              : "CodeIgniter",
    "ci"                        : "CodeIgniter",
    "yii"                       : "Yii",
    "symfony"                   : "Symfony",
    "spring"                    : "Java Spring Boot",
    "spring boot"               : "Java Spring Boot",
    "springboot"                : "Java Spring Boot",
    "spring framework"          : "Spring Framework",
    "asp.net"                   : "ASP.NET",
    "aspnet"                    : "ASP.NET",
    "asp net"                   : "ASP.NET",
    "asp.net mvc"               : "ASP.NET MVC",
    "gin"                       : "Gin",
    "gofiber"                   : "GoFiber",
    "go fiber"                  : "GoFiber",
    "frappe"                    : "Frappe",
    "erpnext"                   : "ERPNext",
    "erp next"                  : "ERPNext",
    "quarkus"                   : "Java Quarkus",
    "java quarkus"              : "Java Quarkus",
    "hibernate"                 : "Hibernate",
    "mybatis"                   : "MyBatis",
    "my batis"                  : "MyBatis",
    "gorm"                      : "GORM",
    "bullmq"                    : "BullMQ",
    "bull mq"                   : "BullMQ",

    # ── Mobile ─────────────────────────────────────────────
    "flutter"                   : "Flutter",
    "dart"                      : "Dart",
    "kotlin"                    : "Kotlin",
    "android"                   : "Java Android",
    "java android"              : "Java Android",
    "react native"              : "React Native",
    "reactnative"               : "React Native",
    "jetpack compose"           : "Jetpack Compose",
    "goroutine"                 : "GoRouter",
    "bloc"                      : "BLoC",
    "getit"                     : "GetIt",
    "get it"                    : "GetIt",
    "gorouter"                  : "GoRouter",
    "go router"                 : "GoRouter",

    # ── Programming Languages ──────────────────────────────
    "python"                    : "Python",
    "java"                      : "Java",
    "javascript"                : "JavaScript",
    "js"                        : "JavaScript",
    "typescript"                : "TypeScript",
    "ts"                        : "TypeScript",
    "php"                       : "PHP",
    "golang"                    : "Golang",
    "go"                        : "Golang",
    "c#"                        : "C#",
    "csharp"                    : "C#",
    "c sharp"                   : "C#",
    "c++"                       : "C++",
    "cpp"                       : "C++",
    "kotlin"                    : "Kotlin",
    "dart"                      : "Dart",
    "r"                         : "R Language",
    "r language"                : "R Language",
    "scala"                     : "Scala",
    "ruby"                      : "Ruby",
    ".net"                      : ".NET Ecosystem",
    "dotnet"                    : ".NET Ecosystem",
    "dot net"                   : ".NET Ecosystem",
    "pascal"                    : "Pascal/Delphi",
    "delphi"                    : "Pascal/Delphi",

    # ── Testing & QA ───────────────────────────────────────
    "junit"                     : "JUnit",
    "jest"                      : "Jest",
    "selenium"                  : "Selenium",
    "appium"                    : "Appium",
    "katalon"                   : "Katalon Studio",
    "jmeter"                    : "JMeter",
    "j meter"                   : "JMeter",
    "burpsuite"                 : "Burp Suite",
    "burp suite"                : "Burp Suite",
    "postman testing"           : "API Testing Tools",
    "e2e"                       : "End-to-End (E2E) Testing",
    "end to end"                : "End-to-End (E2E) Testing",
    "unit test"                 : "Unit Testing",
    "unit testing"              : "Unit Testing",
    "bdd"                       : "BDD",
    "xray"                      : "Xray",
    "bugzilla"                  : "Bugzilla",
    "webdriverio"               : "WebdriverIO (Wdio)",
    "wdio"                      : "WebdriverIO (Wdio)",

    # ── Project Management & Collaboration ─────────────────
    "jira"                      : "JIRA",
    "confluence"                : "Confluence",
    "trello"                    : "Trello",
    "notion"                    : "Notion",
    "slack"                     : "Slack",
    "google docs"               : "Google Docs",
    "google sheets"             : "Google Sheets",
    "google analytics"          : "Google Analytics",
    "scrum"                     : "Scrum Framework",
    "agile"                     : "Agile Methodology",
    "kanban"                    : "Kanban",
    "waterfall"                 : "Waterfall",
    "brd"                       : "BRD",
    "fsd"                       : "FSD",

    # ── UI/UX & Design ─────────────────────────────────────
    "figma"                     : "Figma",
    "canva"                     : "Canva",
    "adobe xd"                  : "Adobe XD",
    "adobexd"                   : "Adobe XD",
    "photoshop"                 : "Adobe Photoshop",
    "adobe photoshop"           : "Adobe Photoshop",
    "illustrator"               : "Adobe Illustrator",
    "adobe illustrator"         : "Adobe Illustrator",
    "balsamiq"                  : "Balsamiq",
    "zeplin"                    : "Zeplin",
    "draw.io"                   : "Draw.io",
    "drawio"                    : "Draw.io",
    "excalidraw"                : "Excalidraw",
    "miro"                      : "Miro",
    "bizagi"                    : "Bizagi",
    "flowchart"                 : "Flowchart",
    "wireframe"                 : "Wireframing & Prototyping Tools",
    "wireframing"               : "Wireframing & Prototyping Tools",
    "prototype"                 : "Wireframing & Prototyping Tools",
    "prototyping"               : "Wireframing & Prototyping Tools",

    # ── Messaging & Streaming ──────────────────────────────
    "kafka"                     : "Kafka",
    "rabbitmq"                  : "RabbitMQ",
    "rabbit mq"                 : "RabbitMQ",
    "activemq"                  : "ActiveMQ",
    "active mq"                 : "ActiveMQ",
    "artemismq"                 : "ArtemisMQ",
    "artemis mq"                : "ArtemisMQ",
    "artemis"                   : "ArtemisMQ",
    "nats"                      : "NATS",
    "drpc"                      : "dRPC",

    # ── Networking & Protocols ─────────────────────────────
    "vpn"                       : "VPN",
    "ftp"                       : "FTP",
    "sftp"                      : "SFTP",
    "tcp"                       : "TCP/IP",
    "tcp/ip"                    : "TCP/IP",
    "nginx"                     : "Nginx",
    "apache"                    : "Apache HTTP Server",

    # ── Software Architecture ──────────────────────────────
    "microservices"             : "Microservices",
    "micro services"            : "Microservices",
    "clean architecture"        : "Architecture Patterns",
    "mvc"                       : "Architecture Patterns",
    "oop"                       : "Design Principles & OOP",
    "solid"                     : "Design Principles & OOP",
    "design pattern"            : "Design Principles & OOP",
    "design patterns"           : "Design Principles & OOP",

    # ── Data Analytics & BI ────────────────────────────────
    "tableau"                   : "Tableau",
    "power bi"                  : "Power BI",
    "powerbi"                   : "Power BI",
    "looker"                    : "Looker Studio",
    "looker studio"             : "Looker Studio",
    "apache superset"           : "Apache Superset",
    "superset"                  : "Apache Superset",
    "jasperreports"             : "JasperReports",
    "jasper"                    : "JasperReports",
    "pandas"                    : "Pandas",
    "numpy"                     : "NumPy",
    "num py"                    : "NumPy",
    "geopandas"                 : "Geopandas",
    "gis"                       : "GIS",
    "google earth engine"       : "Google Earth Engine",
    "geoserver"                 : "GeoServer",

    # ── Low-Code / No-Code ─────────────────────────────────
    "camunda"                   : "Camunda",
    "n8n"                       : "n8n",
    "power automate"            : "Power Automate",
    "powerautomate"             : "Power Automate",
    "retool"                    : "Retool",

    # ── Security ───────────────────────────────────────────
    "bcrypt"                    : "Bcrypt",
    "oauth"                     : "OAuth",
    "oauth2"                    : "OAuth",
    "ssl"                       : "SSL/TLS",
    "tls"                       : "SSL/TLS",
    "ssl/tls"                   : "SSL/TLS",

    # ── Documentation & Diagramming ───────────────────────
    "uml"                       : "UML Diagrams",
    "class diagram"             : "Class Diagram",
    "use case"                  : "Use Case Diagram",
    "use case diagram"          : "Use Case Diagram",
    "sequence diagram"          : "Sequence Diagram",
    "activity diagram"          : "Activity Diagram",
    "erd diagram"               : "ERD",
    "dfd"                       : "DFD",
    "api documentation"         : "API Documentation",
    "api doc"                   : "API Documentation",
    "swagger"                   : "Swagger",
    "openapi"                   : "Swagger",
    "open api"                  : "Swagger",
    "postman doc"               : "API Documentation",
    "google calendar api"       : "Google Calendar API",
    "web3"                      : "Web3.js",
    "web3.js"                   : "Web3.js",
    "yajra"                     : "Yajra Datatables",
    "datatables"                : "Yajra Datatables",
    "lazarus"                   : "Lazarus",
    "javalang"                  : "Javalang",
    "jdepend"                   : "JDepend",
    "excelize"                  : "Excelize",
    "apache poi"                : "Apache POI",
    "poi"                       : "Apache POI",
    "java webmail"              : "Java WebMail",
    "webmail"                   : "Java WebMail",
    "camunda bpmn"              : "Camunda",
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
