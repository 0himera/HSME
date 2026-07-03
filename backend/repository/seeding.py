from backend.core.models import Entity, Experiment

def seed_database(db):
    """Seeds the database with high-quality mock research experiments in the mining-metallurgy domain."""
    mock_experiments = [
        # Series 1: Nickel Electrowinning (Электроэкстракция никеля) - Sensitive
        Experiment(
            id="EXP-NI-01",
            name="Никелевая электроэкстракция в хлоридном электролите при pH 2.0",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 2.0"),
                Entity(type="Property", value="плотность тока: 300 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 72 %"),
                Entity(type="Property", value="Выход по току: 94.5 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.95,
            year=2023,
            geography="RU",
            source_type="Обзор",
            is_sensitive=True
        ),
        Experiment(
            id="EXP-NI-02",
            name="Никелевая электроэкстракция в хлоридном электролите при pH 1.0 (Контрфакт)",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 1.0"),
                Entity(type="Property", value="плотность тока: 300 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 85 %"),
                Entity(type="Property", value="Выход по току: 89.2 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.90,
            year=2023,
            geography="RU",
            source_type="Обзор",
            is_sensitive=True
        ),
        Experiment(
            id="EXP-NI-03",
            name="Никелевая электроэкстракция в хлоридном электролите при высокой плотности тока",
            input_entities=[
                Entity(type="Material", value="Хлоридный электролит никеля"),
                Entity(type="Property", value="pH: 2.0"),
                Entity(type="Property", value="плотность тока: 500 А/м2"),
                Entity(type="Facility", value="Кольская ГМК")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Никелевый катод"),
                Entity(type="Property", value="Светлость поверхности: 51 %"),
                Entity(type="Property", value="Выход по току: 92.1 %")
            ],
            evidence=["ОИП-09-2023"],
            confidence=0.92,
            year=2023,
            geography="RU",
            source_type="Обзор",
            is_sensitive=True
        ),
        
        # Series 2: Copper Electrowinning (Электроэкстракция меди) - Non-Sensitive
        Experiment(
            id="EXP-CU-01",
            name="Медная электроэкстракция из сернокислого раствора",
            input_entities=[
                Entity(type="Material", value="Сернокислый электролит меди"),
                Entity(type="Property", value="Температура: 45°C"),
                Entity(type="Property", value="плотность тока: 250 А/м2"),
                Entity(type="Facility", value="Завод Long Harbour")
            ],
            process_entities=[
                Entity(type="Process", value="Электроэкстракция"),
                Entity(type="Equipment", value="Ванна электроэкстракции")
            ],
            output_entities=[
                Entity(type="Material", value="Медный катод"),
                Entity(type="Property", value="Выход по току: 96.8 %")
            ],
            evidence=["ТИ-01-2017"],
            confidence=0.98,
            year=2017,
            geography="Global",
            source_type="Обзор",
            is_sensitive=False
        ),
        
        # Series 3: Heap Leaching in Cold Climates (Кучное выщелачивание) - Sensitive
        Experiment(
            id="EXP-HL-01",
            name="Кучное выщелачивание бедных медно-никелевых руд при температуре 5°C",
            input_entities=[
                Entity(type="Material", value="Бедная сульфидная медно-никелевая руда"),
                Entity(type="Property", value="Температура: 5°C"),
                Entity(type="Facility", value="рудник Кайерканский")
            ],
            process_entities=[
                Entity(type="Process", value="Кучное выщелачивание"),
                Entity(type="Equipment", value="Оросительные системы")
            ],
            output_entities=[
                Entity(type="Material", value="Продуктивный раствор Ni-Cu"),
                Entity(type="Property", value="Извлечение никеля: 62.4 %")
            ],
            evidence=["ТИ-05-2017"],
            confidence=0.88,
            year=2017,
            geography="RU",
            source_type="Обзор",
            is_sensitive=True
        ),
        Experiment(
            id="EXP-HL-02",
            name="Кучное выщелачивание бедных медно-никелевых руд при температуре 20°C (Теплый сезон)",
            input_entities=[
                Entity(type="Material", value="Бедная сульфидная медно-никелевая руда"),
                Entity(type="Property", value="Температура: 20°C"),
                Entity(type="Facility", value="рудник Кайерканский")
            ],
            process_entities=[
                Entity(type="Process", value="Кучное выщелачивание"),
                Entity(type="Equipment", value="Оросительные системы")
            ],
            output_entities=[
                Entity(type="Material", value="Продуктивный раствор Ni-Cu"),
                Entity(type="Property", value="Извлечение никеля: 74.1 %")
            ],
            evidence=["ТИ-05-2017"],
            confidence=0.90,
            year=2017,
            geography="RU",
            source_type="Обзор",
            is_sensitive=True
        )
    ]
    
    for exp in mock_experiments:
        db.insert_experiment(exp)
