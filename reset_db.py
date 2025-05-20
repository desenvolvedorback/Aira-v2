import sqlite3

# Conecta ao banco
conn = sqlite3.connect('logs.db')  # troque o nome se o seu for diferente
cursor = conn.cursor()

# Limpa todas as tabelas necessárias
cursor.execute("DELETE FROM historico")  # troque "historico" pelo nome da tabela usada

# Salva e fecha
conn.commit()
conn.close()

print("Banco de dados resetado com sucesso!")