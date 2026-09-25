import codecs

with codecs.open('static/ui/app.css', 'a', 'utf-8') as f:
    f.write("\n\n/* Accent bar on the main title */\nheader h1, .fd-title {\n    border-left: 5px solid var(--blue) !important;\n    padding-left: 14px !important;\n    border-radius: 2px !important;\n}\n")

with codecs.open('templates/ui/base.html', 'r', 'utf-8') as f:
    html = f.read()

html = html.replace('?v=12', '?v=13')

with codecs.open('templates/ui/base.html', 'w', 'utf-8') as f:
    f.write(html)
