import codecs

with codecs.open('templates/ui/base.html', 'r', 'utf-8') as f:
    html = f.read()

fonts = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{% static 'ui/app.css' %}?v=12">"""

html = html.replace('<link rel="stylesheet" href="{% static \'ui/app.css\' %}?v=10">', fonts)

with codecs.open('templates/ui/base.html', 'w', 'utf-8') as f:
    f.write(html)

css_overrides = """
/* --- MODERN ENTERPRISE UI UPGRADE --- */
:root {
    --navy: #0f172a;
    --blue: #2563eb;
    --bg: #f8fafc;
    --line: #e2e8f0;
    --text: #1e293b;
    --muted: #64748b;
}

body {
    font-family: 'Inter', 'DM Sans', sans-serif !important;
    background-color: var(--bg) !important;
    color: var(--text) !important;
}

h1, h2, h3, h4, h5, h6, .brand-ww, .vc-plate-text, .panel h3, .welcome h2 {
    font-family: 'Manrope', sans-serif !important;
    letter-spacing: -0.02em !important;
}

.panel, .metrics article, .notice, .form-input, .login-card {
    border: 1px solid rgba(226, 232, 240, 0.8) !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px -1px rgba(0, 0, 0, 0.02) !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    transition: box-shadow 0.2s ease;
}

.panel:hover, .metrics article:hover {
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.04), 0 4px 6px -2px rgba(0, 0, 0, 0.02) !important;
}

.sidebar {
    background: linear-gradient(180deg, #0f172a 0%, #020617 100%) !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
}

nav a.active {
    background: rgba(37, 99, 235, 0.15) !important;
    box-shadow: inset 3px 0 0 #3b82f6 !important;
    color: #ffffff !important;
}

.primary-action, button:not(.side-logout):not(.dashboard-informe-item) {
    background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2), inset 0 1px 0 rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
    border: none !important;
    transition: all 0.2s ease !important;
    text-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.primary-action:hover, button:not(.side-logout):not(.dashboard-informe-item):hover {
    background: linear-gradient(180deg, #60a5fa 0%, #3b82f6 100%) !important;
    box-shadow: 0 6px 8px -1px rgba(37, 99, 235, 0.3) !important;
    transform: translateY(-1px) !important;
}

.table-action {
    background: #3b82f6 !important;
    box-shadow: 0 2px 4px -1px rgba(37, 99, 235, 0.2) !important;
}
.table-action.secondary {
    background: #f1f5f9 !important;
    color: #475569 !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
    border: 1px solid #e2e8f0 !important;
    text-shadow: none !important;
}
.table-action.secondary:hover {
    background: #e2e8f0 !important;
    color: #0f172a !important;
}

input, select, textarea {
    border-radius: 8px !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.02) !important;
    transition: all 0.2s ease;
}

input:focus, select:focus, textarea:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
    outline: none !important;
}

.dashboard-informe-item {
    background: transparent !important;
    border: none !important;
    color: inherit !important;
    box-shadow: none !important;
    text-shadow: none !important;
    text-align: left !important;
}

.dashboard-informe-item:hover {
    background: #f8fafc !important;
    transform: none !important;
    box-shadow: none !important;
    color: #2563eb !important;
}

table {
    width: 100%;
    border-collapse: separate !important;
    border-spacing: 0;
}
th {
    background: #f8fafc;
    padding: 12px 16px !important;
    font-weight: 700;
    color: #64748b;
    border-bottom: 2px solid #e2e8f0;
}
td {
    padding: 16px !important;
    border-bottom: 1px solid #f1f5f9 !important;
    color: #334155;
}
tbody tr:hover {
    background: #f8fafc;
}

.vc {
    border-radius: 12px !important;
    border: 1px solid #e2e8f0 !important;
}
.vc:hover {
    border-color: #cbd5e1 !important;
}
.vc-plate {
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05) !important;
}
"""

with codecs.open('static/ui/app.css', 'a', 'utf-8') as f:
    f.write("\n" + css_overrides)
