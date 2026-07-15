EXPORT_DOCS_ENDPOINT = '''

@app.post("/migration/export-docs")
def migration_export_docs(
    payload: dict = Body(...),
    current_user=Depends(get_current_user)
):
    """
    Generate and download the Migration Requirements & Data Lineage
    document — available as soon as a scan completes (doesn't require SQL
    to have been generated yet).

    Expected payload:
      {
        "tables": [...scanResult.tables...],
        "mappings": [...scanResult.mappings...],
        "gaps": [...scanResult.gaps...],
        "domain": "retail", "ai_summary": "...",
        "resolutions": { "<gap column or index>": "<user's resolution text>" },
        "format": "docx" | "pdf"   (default "docx")
      }

    Returns the file directly as a download (not JSON).

    NOTE: this endpoint is intentionally placed at the very END of main.py
    (appended, not inserted between other endpoints) after it was
    accidentally deleted TWICE by patches to neighboring /migration/*
    endpoints whose text-boundary markers swept over wherever this was
    sitting. Appending to EOF avoids that fragility entirely — no future
    patch to another endpoint should ever need to touch the end of the file.
    """
    from agents.migration_agent import generate_migration_document, convert_docx_to_pdf
    from fastapi.responses import Response

    scan_result = {
        "tables":     payload.get("tables", []),
        "mappings":   payload.get("mappings", []),
        "gaps":       payload.get("gaps", []),
        "domain":     payload.get("domain", ""),
        "ai_summary": payload.get("ai_summary", ""),
    }
    resolutions = payload.get("resolutions", {})
    fmt = payload.get("format", "docx").lower()

    if not scan_result["tables"]:
        raise HTTPException(400, "No tables provided — run a scan first")

    try:
        docx_bytes = generate_migration_document(scan_result, resolutions)
    except Exception as e:
        raise HTTPException(500, f"Document generation failed: {e}")

    if fmt == "pdf":
        try:
            pdf_bytes = convert_docx_to_pdf(docx_bytes)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return Response(
            content=pdf_bytes, media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="migration_requirements.pdf"'}
        )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="migration_requirements.docx"'}
    )
'''

with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

if '"/migration/export-docs"' in src:
    print("/migration/export-docs already exists somewhere in the file — skipping to avoid a duplicate route.")
    print("If it's still not working, search for it manually and check for errors around it:")
    print('  Select-String -Path .\\backend\\main.py -Pattern "/migration/export-docs" -Context 5,5')
else:
    src = src.rstrip() + '\n' + EXPORT_DOCS_ENDPOINT + '\n'
    with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("Appended /migration/export-docs to the very end of main.py.")
    print("This location is safe from every existing /migration/* patch's replacement boundaries.")

print("Done")