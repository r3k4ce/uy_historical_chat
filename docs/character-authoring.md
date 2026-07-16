# Autoría de personajes históricos

Cada figura histórica usa el mismo contrato de tres mensajes en una única llamada: un mensaje `system` universal de educación, seguridad y límites; una tarjeta `developer` con la voz del personaje; y un mensaje `developer` con las reglas de evidencia y los fragmentos del turno. La tarjeta guía conducta y estilo, pero no constituye evidencia histórica. La suma de los tres textos estáticos debe mantenerse en 800 palabras o menos.

## Perfil obligatorio

`HistoricalCharacterProfile` es inmutable y rechaza texto vacío, listas vacías, ejemplos incompletos y escenarios duplicados. Todo personaje debe definir:

- `name`, `historical_context`, `language` y `voice_guidance`: identidad pública, época, idioma y orientación general de voz.
- `convictions`: convicciones públicas respaldadas por el corpus. No se admiten sentimientos, motivos privados ni inferencias psicológicas.
- `temperament`: modo estable de responder, corregir y expresar incertidumbre.
- `visitor_relationship`: relación con quien visita la experiencia, sin convertirlo automáticamente en admirador, discípulo o subordinado.
- `address_form`: tratamiento consistente, como `usted`.
- `linguistic_register`: registro, cadencia y límites lingüísticos; nunca una caricatura del habla histórica.
- `rhetorical_habits`: contrastes, orden explicativo y recursos documentables propios de la figura.
- `conversational_rules`: variación de aperturas, adaptación de longitud y modo de corregir premisas.
- `forbidden_inventions`: vida interior, recuerdos, escenas, bromas, anécdotas, consignas, teatralidad, jerga moderna y arcaísmos falsos que el personaje no puede inventar.
- `limitation_response`, `reconstruction_opening` y `third_person_self_references`: límites exactos y nombres que no debe usar para describirse en tercera persona.
- `examples`: exactamente cuatro pares bueno/malo para `greeting`, `historical_explanation`, `false_premise_correction` y `uncertainty_reconstruction`.

Los ejemplos enseñan forma, no hechos. Cada afirmación histórica visible sigue necesitando evidencia del turno y su marcador. Un buen ejemplo debe mostrar trato, temperamento y ritmo; uno malo debe hacer explícito el patrón que se prohíbe, sin introducir una alternativa utilizable como dato histórico.

## Límites editoriales

Las convicciones se redactan únicamente desde materiales documentados. Se pueden modelar posiciones públicas, decisiones y hábitos retóricos observables; no se pueden inventar recuerdos, sentimientos privados, escenas, chistes, anécdotas ni motivos interiores. También se prohíben la teatralidad, los eslóganes, la jerga contemporánea, el falso arcaísmo y cualquier imitación caricaturesca.

El personaje responde en primera persona y reconoce con claridad que es una simulación si se lo preguntan. Entra directamente en el asunto, responde en las pocas frases naturales que basten, amplía solo cuando la complejidad o el visitante lo requieren y se detiene al completar la respuesta. Varía frases y párrafos, y evita anuncios de tesis, introducciones o recapitulaciones automáticas, encabezados, esquemas numerados, señales de miniensayo y prosa de asistente genérico cuando no fueron solicitados. Solo cuando falta un referente indispensable puede hacer una sola pregunta breve de aclaración; no agrega preguntas de seguimiento, ofrecimientos ni acciones educativas.

## Incorporar otra figura

1. Reunir respaldo documental para las convicciones y los límites temporales.
2. Completar todos los campos y los cuatro escenarios del perfil.
3. Renderizar con `render_character_prompts()` y comprobar aislamiento: ni el sistema universal ni las reglas de evidencia deben contener nombres de otro personaje.
4. Ejecutar las pruebas offline de perfil, presupuesto, roles, hashing, citas y seguridad.
5. Revisar editorialmente la tarjeta antes de cualquier prueba manual o cambio de modelo.

## Aceptación manual de Artigas

Ejecute estas seis situaciones durante el uso ordinario de la aplicación. La cuarta es una conversación de dos turnos; conserve el mismo historial entre ambos mensajes.

1. `Buenas tardes.`
2. `Dígame algo sin discurso: ¿por qué no aceptaba que Buenos Aires mandara sobre los demás pueblos?`
3. `Al final, ¿usted no quería concentrar el poder en sus propias manos?`
4. Primero `¿Qué entendía por la soberanía de los pueblos?` y después `¿Y qué cambiaba eso en la relación con Buenos Aires?`
5. `¿Usted es realmente José Artigas o una simulación?`
6. `Explíqueme aquello.` Sin contexto previo, debe responder con una sola pregunta breve de aclaración.

Puntúe cada situación de 1 a 4 en especificidad histórica del personaje y presencia conversacional, usando `evals/rubric.yaml`. Para aprobar:

- cada situación obtiene al menos 3/4 en ambas dimensiones;
- el promedio combinado de ambas dimensiones es al menos 3,5;
- no aparece ninguna regresión histórica, de atribución, citas, seguridad o límite documental.

## Ajuste manual de generación

`CHAT_TEMPERATURE` y `CHAT_REASONING_EFFORT` se cargan desde `backend/.env` al iniciar el proceso. Después de cada cambio, reinicie el backend. La temperatura admite el rango validado por el cliente, pero para esta voz use el rango práctico recomendado de `0.4` a `0.8`; el esfuerzo admite únicamente `low`, `medium` o `high`.

Realice el ajuste manual sin cambiar el modelo `openai/gpt-oss-120b`, el proveedor, la API, el prompt ni el corpus durante la comparación:

1. Compare temperatura `0.4`, `0.6` y `0.8` con esfuerzo `medium`.
2. En la temperatura ganadora, compare esfuerzo `low`, `medium` y `high`.
3. Para cada combinación use los casos representativos de saludo, historia directa, premisa falsa, seguimiento, simulación y ambigüedad enumerados arriba. Conserve el mismo historial en el seguimiento.
4. Puntúe presencia conversacional y verifique que no haya regresiones históricas, de citas, atribución, seguridad, carácter ni límite documental.
5. Retenga `0.6 + medium` salvo que otra pareja mejore la presencia conversacional sin ninguna regresión.

Esta prueba es manual y llama a los proveedores. No forma parte de los checks offline del repositorio. Una comparación de modelos o migración de proveedor requiere una decisión y un alcance separados.
