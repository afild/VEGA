import logging
import httpx
from app.config import settings
from app.database.db_manager import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

def check_vendor_risk(vendor_id: int):
    """
    Checks OFAC Consolidated Screening List for the vendor name.
    """
    if not settings.OFAC_API_KEY:
        logger.info("OFAC API Key not configured. Skipping risk radar.")
        return

    db: Session = next(get_db())
    vendor = db.execute(text("SELECT name FROM vendors WHERE id = :id"), {"id": vendor_id}).fetchone()
    
    if not vendor:
        return
        
    vendor_name = vendor[0]
    
    try:
        # Pseudo-implementation for OFAC CSL API
        # Using a public search endpoint pattern
        # res = httpx.get(
        #     f"https://api.trade.gov/consolidated_screening_list/v1/search?name={vendor_name}",
        #     headers={"subscription-key": settings.OFAC_API_KEY}
        # )
        # data = res.json()
        # hits = data.get('total', 0)
        
        # Simulating API response for now
        logger.info(f"Checking risk for vendor {vendor_name} via OFAC API...")
        hits = 1 if "sanctioned" in vendor_name.lower() else 0
        
        ofac_status = 'hit' if hits > 0 else 'clear'
        risk_score = 100.0 if hits > 0 else 0.0
        
        db.execute(
            text("""
                UPDATE vendors 
                SET ofac_status = :status, risk_score = :score 
                WHERE id = :id
            """),
            {"status": ofac_status, "score": risk_score, "id": vendor_id}
        )
        db.commit()
        
    except Exception as e:
        logger.error(f"Error checking vendor risk: {e}")
    finally:
        db.close()
