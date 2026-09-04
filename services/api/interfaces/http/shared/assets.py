"""Public images extracted from already-public university notices."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.asset_files import resolve_asset_path
from db.pool import pool

router = APIRouter()


@router.get("/notice-assets/{asset_id}/content")
async def notice_asset_content(asset_id: int) -> FileResponse:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT storage_path,mime_type,filename
               FROM notice_asset
               WHERE id=%s AND kind IN ('attachment_hwp_image','attachment_document_image','inline_image')""",
            (asset_id,),
        )).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="공지 이미지를 찾을 수 없습니다.")
    mime_type = str(row[1] or "")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="이미지 자산이 아닙니다.")
    path = resolve_asset_path(str(row[0]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="공지 이미지가 디스크에 없습니다.")
    return FileResponse(
        path,
        media_type=mime_type,
        filename=str(row[2] or path.name),
        content_disposition_type="inline",
    )
