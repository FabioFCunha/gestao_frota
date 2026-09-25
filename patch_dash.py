import codecs

with codecs.open('templates/ui/dashboard.html', 'r', 'utf-8') as f:
    html = f.read()

# Make panels flex containers
html = html.replace('<article class="panel">', '<article class="panel" style="display:flex; flex-direction:column;">')

# Push the buttons to the bottom
html = html.replace('<div style="margin-top:14px;">\n                <a class="primary-action" href="{% url \'contract_list\' %}"', 
'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'contract_list\' %}"')

html = html.replace('<div style="margin-top:14px;">\n                <a class="primary-action" href="{% url \'fine_list\' %}"', 
'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'fine_list\' %}"')

html = html.replace('<div style="margin-top:14px;">\n                <a class="primary-action" href="{% url \'driver_list\' %}?status=cnh_vencida"', 
'<div style="margin-top:auto; padding-top:14px;">\n                <a class="primary-action" href="{% url \'driver_list\' %}?status=cnh_vencida"')

html = html.replace('<div class="empty" style="margin-top:12px;">', '<div class="empty" style="margin-top:auto; margin-bottom:auto;">')

with codecs.open('templates/ui/dashboard.html', 'w', 'utf-8') as f:
    f.write(html)
