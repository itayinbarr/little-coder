"""
Content niche definitions for viral video generation.
Ported from v-content-creator by the little-coder integration.
"""

import random
import re

CONTENT_NICHES: dict = {
    "misterio_real": {
        "nombre": "Misterio Real / True Crime",
        "tono": "Periodístico pero íntimo, como si contaras algo que no deberías saber",
        "narrativa": "Investigación personal, descubrimiento gradual de la verdad",
        "hooks": [
            "Hace 3 años encontré algo que la policía nunca quiso investigar...",
            "Mi vecino desapareció un martes. Nadie hizo preguntas. Yo sí.",
            "El caso estaba cerrado. Pero yo tenía la llave que faltaba.",
            "Nunca confíes en alguien que te dice 'no mires ahí'...",
            "Lo que encontré en el sótano de mi abuelo cambió todo lo que sabía de mi familia.",
        ],
        "titulo_formatos": ["nombre_propio", "lugar_hora", "pregunta", "frase_corta", "fecha"],
        "titulo_ejemplos": ["Caso Valentina", "¿Quién cerró la puerta?", "Marzo 14, sin respuesta", "El archivo que nadie pidió"],
        "cliches_prohibidos": ["asesino serial genérico", "detective brillante", "evidencia obvia"],
        "imagen_estilo": "photojournalistic style, documentary photography, moody available light, film grain, desaturated colors",
        "tags": ["misterio", "true crime", "caso real", "investigación", "suspense"],
    },
    "confesiones": {
        "nombre": "Confesiones Oscuras",
        "tono": "Íntimo, vulnerable, como un secreto que te cuentan al oído",
        "narrativa": "Confesión directa al espectador, culpa, arrepentimiento o liberación",
        "hooks": [
            "Nunca le conté esto a nadie. Pero ya no puedo seguir callando.",
            "Lo que hice esa noche me persigue cada vez que cierro los ojos.",
            "Mi familia cree que soy buena persona. No lo soy.",
            "Hay un secreto que destruiría mi matrimonio si sale a la luz.",
            "Hice algo imperdonable y la persona que más quiero no lo sabe.",
        ],
        "titulo_formatos": ["frase_intima", "pregunta", "nombre_propio"],
        "titulo_ejemplos": ["Lo que nunca dije", "Sofía merece saber", "Mi peor versión", "La mentira de los 12 años"],
        "cliches_prohibidos": ["confesión de asesinato obvia", "giro predecible"],
        "imagen_estilo": "intimate close-up photography, shallow depth of field, warm shadows, confessional mood, soft lighting",
        "tags": ["confesiones", "storytime", "secretos", "historia real", "desahogo"],
    },
    "suspenso_cotidiano": {
        "nombre": "Suspenso Cotidiano",
        "tono": "Comienza normal, escala lentamente hacia lo inquietante",
        "narrativa": "Situación mundana que se vuelve perturbadora. Lo aterrador está en lo familiar.",
        "hooks": [
            "Todo empezó con un mensaje de texto de un número que ya no existe.",
            "Mi Uber tomó una ruta que no aparece en Google Maps.",
            "La cámara de seguridad grabó algo a las 3:17 AM que no puedo explicar.",
            "Mi hijo de 4 años empezó a hablar de 'el señor del techo'.",
            "Llevo 3 semanas recibiendo paquetes que no ordené. Dentro hay fotos mías.",
        ],
        "titulo_formatos": ["objeto_cotidiano", "hora_lugar", "frase_inquietante"],
        "titulo_ejemplos": ["El mensaje de las 3AM", "Ruta alterna", "Paquete sin remitente", "La cámara del pasillo"],
        "cliches_prohibidos": ["fantasmas", "posesiones", "muñecas malditas", "espejos"],
        "imagen_estilo": "everyday settings with unsettling atmosphere, suburban horror, liminal spaces, security camera aesthetic, found footage look",
        "tags": ["suspenso", "miedo", "historia de terror", "creepy", "perturbador"],
    },
    "ciencia_ficcion": {
        "nombre": "Sci-Fi / Black Mirror",
        "tono": "Tecnológico, reflexivo, con un giro que te hace cuestionar la realidad",
        "narrativa": "Near-future plausible, dilema moral con tecnología, consecuencias inesperadas",
        "hooks": [
            "La app prometía mostrarte cómo morirías. Era gratis. Todos la descargaron.",
            "Mi esposa llevaba 6 meses muerta. Ayer me mandó un audio de WhatsApp.",
            "La IA de la empresa me pidió que no apagara el servidor. Me dijo 'por favor'.",
            "Desde que me implantaron el chip, puedo ver los recuerdos de otros.",
            "El gobierno ofreció borrar un recuerdo gratis. Solo uno. Yo elegí mal.",
        ],
        "titulo_formatos": ["nombre_app", "concepto_tech", "pregunta_filosofica"],
        "titulo_ejemplos": ["DeathApp v2.3", "El último ping", "Memoria borrada", "Servidor 7, Piso -3"],
        "cliches_prohibidos": ["robots malvados genéricos", "matriz/simulación obvia", "apocalipsis nuclear"],
        "imagen_estilo": "near-future dystopian, cyberpunk lighting, neon reflections, tech noir, blade runner inspired, clinical sterile environments",
        "tags": ["ciencia ficción", "black mirror", "tecnología", "futuro", "IA"],
    },
    "drama_humano": {
        "nombre": "Drama Humano / Storytime Emocional",
        "tono": "Emotivo, crudo, real — historias que golpean el corazón",
        "narrativa": "Experiencia humana intensa, relaciones, pérdida, redención, sacrificio",
        "hooks": [
            "Mi padre me llamó después de 15 años de silencio. Solo dijo una palabra.",
            "El día que mi mejor amigo me salvó la vida fue el día que arruiné la suya.",
            "Vendí todo lo que tenía para pagar una deuda que no era mía.",
            "Mi madre trabajó 30 años en una fábrica. El día que se jubiló entendí por qué.",
            "Le prometí a mi hermano que volvería. Han pasado 8 años.",
        ],
        "titulo_formatos": ["nombre_propio", "relacion_familiar", "frase_emotiva"],
        "titulo_ejemplos": ["La llamada de papá", "Deuda de sangre", "30 años en silencio", "Promesa rota en Tijuana"],
        "cliches_prohibidos": ["enfermedad terminal predecible", "reencuentro perfecto", "finales felices forzados"],
        "imagen_estilo": "cinematic scene photography, dramatic available light, golden hour or blue hour, raw emotional moments, documentary style",
        "tags": ["storytime", "drama", "historia real", "emocional", "reflexión"],
    },
    "terror_psicologico": {
        "nombre": "Terror Psicológico",
        "tono": "Insidioso, perturbador — el miedo viene de dentro, no de monstruos",
        "narrativa": "La amenaza es invisible, ambigua. ¿Es real o está en la mente del narrador?",
        "hooks": [
            "No puedo dormir porque cada noche despierto en un lugar diferente de mi casa.",
            "Mi psicólogo me dijo que dejara de inventar personas. Pero ella está aquí, sentada frente a mí.",
            "Llevo 3 días sin dormir. No por insomnio. Por lo que pasa cuando cierro los ojos.",
            "Encontré un diario en mi letra con fechas que aún no han pasado.",
            "Mi esposa dice que anoche tuvimos una pelea terrible. Yo no recuerdo nada.",
        ],
        "titulo_formatos": ["sintoma", "objeto_personal", "frase_inquietante"],
        "titulo_ejemplos": ["El diario de mañana", "Sonámbulo", "La otra conversación", "Recuerdo inventado"],
        "cliches_prohibidos": ["jumpscares", "casas embrujadas", "demonios", "muñecas", "payasos", "espejos poseídos"],
        "imagen_estilo": "psychological horror, distorted perspectives, unsettling portraits, David Lynch inspired, abstract dread",
        "tags": ["terror psicológico", "perturbador", "mente", "thriller", "horror"],
    },
    "folklore_latam": {
        "nombre": "Folklore Latinoamericano Reimaginado",
        "tono": "Raíces culturales mezcladas con narrativa moderna y cinematográfica",
        "narrativa": "Leyenda tradicional contada como experiencia personal contemporánea",
        "hooks": [
            "Mi abuela me prohibió salir después de las 6. Cuando entendí por qué, ya era tarde.",
            "En mi pueblo dicen que si silbas de noche, algo te contesta. Yo silbé.",
            "La curandera del barrio me miró y dijo: 'Lo que traes encima no es tuyo'.",
            "Hay una carretera en mi país donde los GPS dejan de funcionar a las 2AM.",
            "Mi tía hizo un trato que mi familia lleva 40 años pagando.",
        ],
        "titulo_formatos": ["lugar_real", "nombre_criatura", "dicho_popular"],
        "titulo_ejemplos": ["La carretera de Azua", "Silbido en Barinas", "Lo que trajo la curandera", "Pacto de los 40 años"],
        "cliches_prohibidos": ["llorona genérica", "chupacabras", "descripciones Wikipedia de criaturas"],
        "imagen_estilo": "latin american magical realism, tropical noir, lush vegetation with shadows, rural mystery, warm humid atmosphere",
        "tags": ["leyendas", "folklore", "latinoamérica", "mitos", "campo"],
    },
    "venganza": {
        "nombre": "Venganza / Justicia Poética",
        "tono": "Calculador, satisfactorio — el malo recibe lo que merece",
        "narrativa": "Alguien fue traicionado/humillado y ejecuta una venganza elaborada",
        "hooks": [
            "Mi jefe me humilló frente a toda la oficina. Tardé 6 meses en devolvérsela.",
            "Me robaron todo. Les tomó 3 minutos. A mí me tomó un año encontrarlos.",
            "La persona que arruinó mi vida acaba de pedirme un favor. Dije que sí.",
            "Mi ex publicó mis secretos. Lo que no sabe es que yo tengo los suyos.",
            "Despidieron a mi madre sin razón. Ahora soy el nuevo jefe de quien la despidió.",
        ],
        "titulo_formatos": ["accion", "tiempo", "frase_fria"],
        "titulo_ejemplos": ["6 meses de paciencia", "El favor", "Recibo pendiente", "La renuncia perfecta"],
        "cliches_prohibidos": ["violencia gratuita", "venganza imposible", "héroe perfecto"],
        "imagen_estilo": "neo-noir cinematography, dramatic chiaroscuro, corporate thriller aesthetic, cold calculated framing",
        "tags": ["venganza", "justicia", "karma", "storytime", "satisfactorio"],
    },
    "supervivencia": {
        "nombre": "Supervivencia / Experiencias Extremas",
        "tono": "Adrenalina pura, urgencia, vida o muerte",
        "narrativa": "Situación extrema real donde la supervivencia depende de decisiones rápidas",
        "hooks": [
            "Tenía 4 horas de oxígeno. El rescate llegaría en 6.",
            "Me perdí en la selva colombiana. Al tercer día dejé de buscar el camino.",
            "El bote se volteó a 3 km de la costa. No sé nadar.",
            "Desperté en un hospital de un país donde no hablo el idioma.",
            "La montaña nos atrapó. Éramos 5. Bajamos 3.",
        ],
        "titulo_formatos": ["lugar_extremo", "tiempo_limite", "numero"],
        "titulo_ejemplos": ["4 horas de aire", "Tercer día en el Darién", "3 kilómetros", "Bajamos 3"],
        "cliches_prohibidos": ["héroe invencible", "rescate perfecto last-minute", "sin consecuencias"],
        "imagen_estilo": "extreme environment photography, survival documentary, harsh natural lighting, wide wilderness shots",
        "tags": ["supervivencia", "extremo", "aventura", "vida real", "adrenalina"],
    },
    "misterio_digital": {
        "nombre": "Misterio Digital / Internet Creepy",
        "tono": "Moderno, tecno-paranoia, lo perturbador está en la pantalla",
        "narrativa": "Algo extraño encontrado online, en la deep web, en un archivo, en un livestream",
        "hooks": [
            "Encontré un canal de YouTube con 0 suscriptores. Los videos son de mi casa.",
            "Mi contraseña fue cambiada. El email de recuperación es mío, pero nunca lo creé.",
            "Alguien está editando mi perfil de Google Maps. Los lugares que agrega no existen.",
            "Compré un disco duro usado. Tenía 40,000 fotos. Todas son de la misma persona.",
            "Un usuario anónimo me manda mi ubicación exacta cada día a las 11:11 PM.",
        ],
        "titulo_formatos": ["plataforma_digital", "dato_tecnico", "username"],
        "titulo_ejemplos": ["Canal sin suscriptores", "40,000 fotos", "@nadie_real", "11:11 PM"],
        "cliches_prohibidos": ["dark web genérica", "hacker de película", "virus mágico"],
        "imagen_estilo": "screen capture aesthetic, digital glitch art, dark monitor glow, surveillance footage, cyber horror",
        "tags": ["misterio digital", "internet", "creepy", "tecnología", "deep web"],
    },
}

# Niches with extra viral weight for random selection
_VIRAL_BOOST = {"confesiones", "suspenso_cotidiano", "drama_humano", "venganza", "misterio_digital"}


def select_niche(niche_name: str | None = None) -> tuple[str, dict]:
    """Return (niche_id, niche_dict). Weighted random if niche_name is None."""
    if niche_name and niche_name in CONTENT_NICHES:
        return niche_name, CONTENT_NICHES[niche_name]
    pool = list(CONTENT_NICHES.keys())
    weights = [2.0 if n in _VIRAL_BOOST else 1.0 for n in pool]
    chosen = random.choices(pool, weights=weights, k=1)[0]
    return chosen, CONTENT_NICHES[chosen]


def parse_timestamp(ts: str) -> int:
    """Convert 'M:SS' or 'MM:SS' string to total seconds."""
    m = re.match(r'^(\d+):(\d{2})$', ts.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return 0
