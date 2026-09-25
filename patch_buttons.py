import re
import codecs

with codecs.open('templates/ui/dashboard.html', 'r', 'utf-8') as f:
    html = f.read()

# Fix the button wrappers
html = re.sub(r'<div style="margin-top:14px;">\s*<a class="primary-action" href="\{% url \'contract_list\' %\}', 
    r'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'contract_list\' %}', html)

html = re.sub(r'<div style="margin-top:14px;">\s*<a class="primary-action" href="\{% url \'fine_list\' %\}', 
    r'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'fine_list\' %}', html)

html = re.sub(r'<div style="margin-top:14px;">\s*<a class="primary-action" href="\{% url \'driver_list\' %\}\?status=cnh_vencida"', 
    r'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'driver_list\' %}?status=cnh_vencida"', html)

# Make sure primary-action buttons all have exactly the same height padding and align nicely
# They already use class="primary-action"

with codecs.open('templates/ui/dashboard.html', 'w', 'utf-8') as f:
    f.write(html)

# Add CSS for uniform filter chips
css_extra = """
/* Uniform filter chips */
.fd-chip {
    height: 44px !important;
    min-width: 150px !important;
    justify-content: center !important;
    padding: 0 16px !important;
}
"""

with codecs.open('static/ui/app.css', 'a', 'utf-8') as f:
    f.write(css_extra)

