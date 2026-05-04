from app.extensions import db

from .models import Nutrient, NutrientCategory

# Macronutrientes
macronutrients = [
    {
        "name": "Nitrógeno",
        "symbol": "N",
        "unit": "kg/ha",
        "description": "Esencial para el crecimiento vegetativo y el desarrollo de hojas",
        "category": NutrientCategory.MACRONUTRIENT,
    },
    {
        "name": "Fósforo",
        "symbol": "P",
        "unit": "kg/ha",
        "description": "Importante para el desarrollo de raíces y flores",
        "category": NutrientCategory.MACRONUTRIENT,
    },
    {
        "name": "Potasio",
        "symbol": "K",
        "unit": "kg/ha",
        "description": "Mejora la resistencia a enfermedades y el rendimiento",
        "category": NutrientCategory.MACRONUTRIENT,
    },
    {
        "name": "Calcio",
        "symbol": "Ca",
        "unit": "kg/ha",
        "description": "Fundamental para el desarrollo de células y paredes celulares",
        "category": NutrientCategory.MACRONUTRIENT,
    },
    {
        "name": "Magnesio",
        "symbol": "Mg",
        "unit": "kg/ha",
        "description": "Esencial para la fotosíntesis y el metabolismo energético",
        "category": NutrientCategory.MACRONUTRIENT,
    },
    {
        "name": "Azufre",
        "symbol": "S",
        "unit": "kg/ha",
        "description": "Importante para la formación de aminoácidos y enzimas",
        "category": NutrientCategory.MACRONUTRIENT,
    },
]

# Micronutrientes
micronutrients = [
    {
        "name": "Cobre",
        "symbol": "Cu",
        "unit": "g/ha",
        "description": "Actúa como cofactor en varias enzimas",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Zinc",
        "symbol": "Zn",
        "unit": "g/ha",
        "description": "Importante para la regulación génica y el crecimiento",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Manganeso",
        "symbol": "Mn",
        "unit": "g/ha",
        "description": "Participa en la fotosíntesis y el metabolismo de carbohidratos",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Boro",
        "symbol": "B",
        "unit": "g/ha",
        "description": "Importante para la pared celular y el transporte de azúcares",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Molibdeno",
        "symbol": "Mo",
        "unit": "g/ha",
        "description": "Esfuerzo en la fijación de nitrógeno y metabolismo del azufre",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Cloro",
        "symbol": "Cl",
        "unit": "g/ha",
        "description": "Importante para la osmoregulación y el rendimiento",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Hierro",
        "symbol": "Fe",
        "unit": "g/ha",
        "description": "Componente clave de las enzimas respiratorias",
        "category": NutrientCategory.MICRONUTRIENT,
    },
    {
        "name": "Silicio",
        "symbol": "Si",
        "unit": "kg/ha",
        "description": "Mejora la estructura de las plantas y su resistencia",
        "category": NutrientCategory.MICRONUTRIENT,
    },
]


def initialize_nutrients():
    """Initialize the nutrients table with default values"""
    # Verificar si ya existen nutrientes
    if Nutrient.query.count() == 0:

        try:
            # Add macronutrients
            for nutrient_data in macronutrients:
                nutrient = Nutrient(
                    name=nutrient_data["name"],
                    symbol=nutrient_data["symbol"],
                    unit=nutrient_data["unit"],
                    description=nutrient_data["description"],
                    category=nutrient_data["category"],
                )
                db.session.add(nutrient)

            # Add micronutrients
            for nutrient_data in micronutrients:
                nutrient = Nutrient(
                    name=nutrient_data["name"],
                    symbol=nutrient_data["symbol"],
                    unit=nutrient_data["unit"],
                    description=nutrient_data["description"],
                    category=nutrient_data["category"],
                )
                db.session.add(nutrient)

            db.session.commit()
            print("Nutrients initialized successfully")

        except Exception as e:
            db.session.rollback()
            print(f"Error initializing nutrients: {str(e)}")
    else:
        print("Nutrients already initialized")
